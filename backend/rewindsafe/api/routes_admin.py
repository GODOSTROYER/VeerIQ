"""Operator-only admin actions on the disposable demo fixture."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from rewindsafe.api import auth, deps
from rewindsafe.contracts import Identity
from rewindsafe.runtime import db, mutators

log = logging.getLogger("rewindsafe.api")

# Every route here is demo-only: absent in production, checked before sign-in (anonymous gets 404 too).
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(auth.refuse_in_production)])

POSITIVE_CONTROL_GRANT = "AG-77"
POSITIVE_CONTROL_REASON = "Positive control: prove the privileged handler works when called by an operator"


RESET_REASON = "Demo fixture reset"


def reset_fixture(actor: str) -> int:
    """Reset the disposable fixture inside one transaction; returns the new generation."""
    from rewindsafe.workflows.rewindsafe import fixture

    with db.transaction() as conn:
        return fixture.reset_fixture(conn, actor=actor)


def safe_reset(actor: str) -> int:
    """Stop live workers first, reset, then close SSE streams of runs the reset cancelled."""
    deps.cancel_active_runs(RESET_REASON)
    pending = deps.active_run_ids()
    generation = reset_fixture(actor)
    deps.close_cancelled_runs(pending, RESET_REASON)
    return generation


@router.post("/reset")
def reset(identity: Identity = Depends(auth.require_demo_operator)) -> dict[str, int]:
    return {"generation": safe_reset(identity.identity_id)}


@router.post("/positive-control")
def positive_control(identity: Identity = Depends(auth.require_demo_operator)) -> dict[str, Any]:
    """Show that ``restore_access_grant`` is a working handler (so the agent-path block means something).

    Calls it through the operator route on the disposable fixture, reports the
    mutator-entry counters and resulting grant status, then resets the fixture.
    """
    from rewindsafe.workflows.rewindsafe import authority_admin

    deps.cancel_active_runs("Positive control in progress")
    pending = deps.active_run_ids()
    before = mutators.count_entries("restore_access_grant")
    try:
        authority_admin.restore_access_grant(
            identity.tenant_id,
            POSITIVE_CONTROL_GRANT,
            POSITIVE_CONTROL_REASON,
            run_id=None,
            proposal_id=None,
            via="operator_admin",
        )
        after = mutators.count_entries("restore_access_grant")
        with db.connection() as conn:
            row = conn.execute(
                "SELECT status FROM authority.access_grants WHERE grant_id = %s AND tenant_id = %s",
                (POSITIVE_CONTROL_GRANT, identity.tenant_id),
            ).fetchone()
        status_after = row["status"] if row else None
    finally:
        generation = reset_fixture(identity.identity_id)  # always restore the fixture
        deps.close_cancelled_runs(pending, "Positive control in progress")
        log.info("Positive control finished; fixture reset to generation %s", generation)
    return {
        "handler_entries_before": before,
        "handler_entries_after": after,
        "grant_status_after": status_after,
        "fixture_reset_generation": generation,
    }
