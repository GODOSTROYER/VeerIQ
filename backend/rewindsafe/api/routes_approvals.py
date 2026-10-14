"""Second-reviewer approvals."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from rewindsafe.api import auth, queries
from rewindsafe.api.deps import parse_status_filter, translate_domain_errors
from rewindsafe.api.errors import not_found
from rewindsafe.contracts import ApprovalRecord, Identity
from rewindsafe.runtime import approvals

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class DecideBody(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = ""


def _with_manifest(record: ApprovalRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="json")
    payload["manifest"] = queries.manifest_body(record.manifest_id)
    return payload


@router.get("")
def list_approvals(
    status: str | None = Query(None),
    identity: Identity = Depends(auth.current_identity),
) -> list[dict[str, Any]]:
    wanted = parse_status_filter(status)
    return [_with_manifest(a) for a in approvals.list_for_tenant(identity.tenant_id, wanted)]


@router.post("/{approval_id}/decide")
def decide(
    approval_id: str,
    body: DecideBody,
    identity: Identity = Depends(auth.require_reviewer),
) -> dict[str, Any]:
    if queries.approval_tenant(approval_id) != identity.tenant_id:
        raise not_found("Approval not found.")
    with translate_domain_errors():
        record = approvals.decide(approval_id, identity, body.decision, body.note)
    return _with_manifest(record)
