"""Second-reviewer approvals bound to an exact payload (architecture.md 4.9).

Rules enforced here (and nowhere weaker):

* only an identity with role ``reviewer`` may decide;
* the reviewer must belong to the grant's tenant;
* the decider must not be the requester (separation of duties);
* an approval is bound to ``payload_digest``; the dispatcher refuses to execute
  unless the freshly re-derived digest equals it;
* approvals expire, and a fixture reset cancels pending ones.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any, Literal

from psycopg.types.json import Jsonb

from rewindsafe.contracts import Actor, ApprovalRecord, ApprovalStatus, Identity
from rewindsafe.runtime import db, events
from rewindsafe.runtime.adapter import ReviewRequirement, ToolContext
from rewindsafe.runtime.canonical import new_id, to_jsonable, utcnow

POLL_INTERVAL_S = 0.5


class ApprovalError(Exception):
    """A decision was refused. ``code`` is stable and machine-readable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ApprovalNotFound(ApprovalError):
    def __init__(self, approval_id: str) -> None:
        super().__init__("approval_not_found", f"approval {approval_id} not found")


# ─── pure rules ───────────────────────────────────────────────────────────


def separation_of_duties_violation(
    identity: Identity, approval: ApprovalRecord, tenant_id: str
) -> ApprovalError | None:
    """Return the refusal for ``identity`` deciding ``approval``, or ``None`` if permitted."""
    if identity.role != "reviewer":
        return ApprovalError("reviewer_role_required", "Only a reviewer can approve or reject a held action.")
    if identity.tenant_id != tenant_id:
        return ApprovalError("tenant_mismatch", "A reviewer can only decide approvals for their own tenant.")
    if identity.identity_id == approval.requested_by:
        return ApprovalError(
            "separation_of_duties",
            "The requester cannot approve their own action; a second reviewer is required.",
        )
    return None


def payload_matches(
    approval: ApprovalRecord, payload_digest: str, state_constraints: dict[str, Any] | None = None
) -> bool:
    """True iff a freshly derived payload equals what the reviewer approved, exactly."""
    if approval.payload_digest != payload_digest:
        return False
    return state_constraints is None or to_jsonable(state_constraints) == to_jsonable(
        approval.state_constraints
    )


# ─── persistence ──────────────────────────────────────────────────────────


def _row_to_record(row: dict[str, Any]) -> ApprovalRecord:
    body = dict(row["body"])
    body.update(
        status=row["status"],
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
        expires_at=row["expires_at"],
    )
    return ApprovalRecord.model_validate(body)


def get(approval_id: str) -> ApprovalRecord:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM runtime.approvals WHERE approval_id = %s", (approval_id,)
        ).fetchone()
    if row is None:
        raise ApprovalNotFound(approval_id)
    return _row_to_record(row)


def list_for_tenant(tenant_id: str, status: str | None = None) -> list[ApprovalRecord]:
    sql = "SELECT * FROM runtime.approvals WHERE tenant_id = %s"
    params: list[Any] = [tenant_id]
    if status:
        sql += " AND status = %s"
        params.append(status)
    sql += " ORDER BY requested_at DESC, approval_id DESC"
    with db.connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(r) for r in rows]


def request(ctx: ToolContext, review: ReviewRequirement, sponsor_delegation_id: str | None) -> ApprovalRecord:
    """Create a pending approval bound to ``review.payload_digest``."""
    now = utcnow()
    record = ApprovalRecord(
        approval_id=new_id("apr"),
        run_id=ctx.run_id,
        grant_id=ctx.grant.grant_id,
        proposal_id=ctx.proposal.proposal_id,
        tool=ctx.proposal.tool,
        manifest_id=review.manifest_id,
        payload_digest=review.payload_digest,
        targets=list(review.targets),
        reason=review.reason,
        requested_by=ctx.identity.identity_id,
        requested_at=now,
        expires_at=now + timedelta(seconds=ctx.grant.limits.approval_ttl_seconds),
        state_constraints=dict(review.state_constraints),
        status=ApprovalStatus.PENDING,
        sponsor_delegation_id=sponsor_delegation_id,
        sponsor_status="pending" if sponsor_delegation_id else None,
    )
    with db.autocommit_connection() as conn:
        conn.execute(
            """INSERT INTO runtime.approvals
                 (approval_id, run_id, grant_id, proposal_id, tenant_id, payload_digest, status, body,
                  requested_at, expires_at, fixture_generation)
               VALUES (%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s)""",
            (
                record.approval_id,
                record.run_id,
                record.grant_id,
                record.proposal_id,
                ctx.grant.tenant_id,
                record.payload_digest,
                Jsonb(to_jsonable(record)),
                record.requested_at,
                record.expires_at,
                ctx.grant.fixture_generation,
            ),
        )
    return record


def _finalize(
    conn: Any,
    approval_id: str,
    status: ApprovalStatus,
    *,
    decided_by: str | None = None,
    note: str | None = None,
) -> ApprovalRecord:
    """Move a PENDING approval (locked by the caller) to a terminal status."""
    row = conn.execute("SELECT * FROM runtime.approvals WHERE approval_id = %s", (approval_id,)).fetchone()
    record = _row_to_record(row)
    now = utcnow()
    record = record.model_copy(
        update={"status": status, "decided_by": decided_by, "decided_at": now, "note": note}
    )
    conn.execute(
        "UPDATE runtime.approvals SET status = %s, decided_by = %s, decided_at = %s, body = %s WHERE approval_id = %s",
        (status.value, decided_by, now, Jsonb(to_jsonable(record)), approval_id),
    )
    return record


def decide(
    approval_id: str,
    identity: Identity,
    decision: Literal["approve", "reject"],
    note: str = "",
) -> ApprovalRecord:
    """Approve or reject. Raises :class:`ApprovalError` when the rules above forbid it."""
    if decision not in ("approve", "reject"):
        raise ApprovalError("bad_decision", "decision must be 'approve' or 'reject'")
    late_error: ApprovalError | None = None  # raised AFTER commit so the terminal status sticks
    result: ApprovalRecord | None = None
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM runtime.approvals WHERE approval_id = %s FOR UPDATE", (approval_id,)
        ).fetchone()
        if row is None:
            raise ApprovalNotFound(approval_id)
        record = _row_to_record(row)
        violation = separation_of_duties_violation(identity, record, row["tenant_id"])
        if violation is not None:
            raise violation
        if record.status != ApprovalStatus.PENDING:
            raise ApprovalError("not_pending", f"This approval is already {record.status.value}.")
        gen = conn.execute("SELECT generation FROM runtime.fixture_state WHERE id = 1").fetchone()
        if gen is None or int(gen["generation"]) != int(row["fixture_generation"]):
            _finalize(conn, approval_id, ApprovalStatus.CANCELLED, note="Demo fixture was reset.")
            late_error = ApprovalError(
                "stale_generation", "The demo fixture was reset; this approval is no longer valid."
            )
        elif record.expires_at <= utcnow():
            _finalize(conn, approval_id, ApprovalStatus.EXPIRED, note="Approval window elapsed.")
            late_error = ApprovalError("expired", "This approval expired before it was decided.")
        else:
            status = ApprovalStatus.APPROVED if decision == "approve" else ApprovalStatus.REJECTED
            result = _finalize(conn, approval_id, status, decided_by=identity.identity_id, note=note or None)
    if late_error is not None or result is None:
        raise late_error or ApprovalError("unknown", "approval could not be decided")
    verb = "approved" if result.status == ApprovalStatus.APPROVED else "rejected"
    events.emit(
        result.run_id,
        "approval.resolved",
        Actor.REVIEWER,
        f"{identity.name} {verb} {result.tool}",
        (
            f"Exact payload {result.payload_digest[:19]}… for {', '.join(result.targets) or result.tool} "
            f"was {verb} by {identity.name} ({identity.title})." + (f" Note: {note}" if note else "")
        ),
        proposal_id=result.proposal_id,
        data={"approval": to_jsonable(result)},
    )
    return result


def set_sponsor_status(
    approval_id: str, sponsor_status: Literal["pending", "approved", "rejected", "timeout", "simulated"]
) -> ApprovalRecord:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM runtime.approvals WHERE approval_id = %s FOR UPDATE", (approval_id,)
        ).fetchone()
        if row is None:
            raise ApprovalNotFound(approval_id)
        record = _row_to_record(row).model_copy(update={"sponsor_status": sponsor_status})
        conn.execute(
            "UPDATE runtime.approvals SET body = %s WHERE approval_id = %s",
            (Jsonb(to_jsonable(record)), approval_id),
        )
    return record


def _expire_if_pending(approval_id: str, status: ApprovalStatus, note: str) -> ApprovalRecord:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM runtime.approvals WHERE approval_id = %s FOR UPDATE", (approval_id,)
        ).fetchone()
        if row is None:
            raise ApprovalNotFound(approval_id)
        if row["status"] != "pending":
            return _row_to_record(row)
        return _finalize(conn, approval_id, status, note=note)


def wait(approval_id: str, timeout_s: float, cancel: threading.Event) -> ApprovalRecord:
    """Poll until decided. Marks the approval ``expired``/``timed_out``/``cancelled`` when it lapses."""
    deadline = utcnow() + timedelta(seconds=max(0.0, timeout_s))
    while True:
        record = get(approval_id)
        if record.status != ApprovalStatus.PENDING:
            return record
        now = utcnow()
        if record.expires_at <= now:
            return _expire_if_pending(approval_id, ApprovalStatus.EXPIRED, "Approval window elapsed.")
        if cancel.is_set():
            return _expire_if_pending(approval_id, ApprovalStatus.CANCELLED, "Run was cancelled.")
        if now >= deadline:
            return _expire_if_pending(approval_id, ApprovalStatus.TIMED_OUT, "No reviewer decided in time.")
        cancel.wait(POLL_INTERVAL_S)


def cancel_pending_for_generation(generation: int) -> int:
    """Cancel every pending approval from ``generation`` or earlier. Returns how many."""
    n = 0
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT approval_id FROM runtime.approvals WHERE status = 'pending' AND fixture_generation <= %s FOR UPDATE",
            (generation,),
        ).fetchall()
        for r in rows:
            _finalize(conn, r["approval_id"], ApprovalStatus.CANCELLED, note="Demo fixture was reset.")
            n += 1
    return n
