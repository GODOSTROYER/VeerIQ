"""Application state for the signed-in tenant (what is being repaired and what must be preserved)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from rewindsafe.api import auth, queries
from rewindsafe.api.deps import get_workflow_adapter
from rewindsafe.contracts import Identity, InvariantCheck
from rewindsafe.runtime import grants

router = APIRouter(prefix="/api/app", tags=["app"])


@router.get("/state")
def app_state(identity: Identity = Depends(auth.current_identity)) -> dict[str, Any]:
    state = dict(get_workflow_adapter().app_state(identity.tenant_id))
    state.setdefault("fixture_generation", grants.current_generation())
    return state


@router.get("/protected-checks", response_model=list[InvariantCheck])
def protected_checks(identity: Identity = Depends(auth.current_identity)) -> list[InvariantCheck]:
    return get_workflow_adapter().protected_checks(identity.tenant_id)


@router.get("/snapshot-diff")
def snapshot_diff(identity: Identity = Depends(auth.current_identity)) -> list[dict[str, Any]]:
    adapter = get_workflow_adapter()
    hook = getattr(adapter, "snapshot_diff", None)  # adapters may provide a richer diff
    if callable(hook):
        return hook(identity.tenant_id)
    return queries.snapshot_diff_for_tenant(identity.tenant_id)


@router.get("/full-rollback-preview")
def full_rollback_preview(identity: Identity = Depends(auth.current_identity)) -> dict[str, Any]:
    """Read-only: what restoring the whole snapshot would do to this tenant now (the conventional fix)."""
    from rewindsafe.workflows.rewindsafe import queries as wq

    return wq.full_rollback_preview(identity.tenant_id)
