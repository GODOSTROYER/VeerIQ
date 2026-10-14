"""Append-only run events (architecture.md 4.3).

Events are written on an autocommit connection so they are visible to other
connections immediately and survive a rolled-back business transaction.
"""

from __future__ import annotations

from psycopg.types.json import Jsonb

from rewindsafe.contracts import Actor, Decision, RunEvent
from rewindsafe.runtime import db
from rewindsafe.runtime.canonical import redact_secrets, redact_text, to_jsonable, utcnow

EVENT_TYPES = frozenset(
    {
        "run.created",
        "run.status",
        "plan.requested",
        "plan.bound",
        "plan.bind_failed",
        "agent.note",
        "agent.proposal",
        "decision",
        "tool.result",
        "manifest.prepared",
        "approval.requested",
        "approval.resolved",
        "execution.committed",
        "execution.rejected",
        "execution.duplicate",
        "replan",
        "external.change",
        "state.changed",
        "telemetry.delivery",
        "run.finished",
    }
)


def emit(
    run_id: str,
    type: str,
    actor: Actor,
    title: str,
    detail: str = "",
    *,
    proposal_id: str | None = None,
    decision: Decision | None = None,
    data: dict | None = None,
) -> RunEvent:
    """Persist one event and return it with its assigned ``seq``."""
    if type not in EVENT_TYPES:
        raise ValueError(f"unknown event type {type!r}; the list is closed (see architecture.md 4.3)")
    ts = utcnow()
    body = {
        "run_id": run_id,
        "ts": ts,
        "type": type,
        "actor": actor,
        "title": redact_text(title),
        "detail": redact_text(detail),
        "proposal_id": proposal_id,
        "decision": to_jsonable(decision) if decision is not None else None,
        "data": redact_secrets(data or {}),
    }
    stored = to_jsonable(body)
    with db.autocommit_connection() as conn:
        # Serialize allocation + commit per run: a higher seq can never become visible before a
        # lower one, so an SSE client resuming with ``seq > after`` cannot skip an event.
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"rs-events:{run_id}",))
            row = conn.execute(
                "INSERT INTO runtime.events (run_id, event_type, body) VALUES (%s, %s, %s) RETURNING seq",
                (run_id, type, Jsonb(stored)),
            ).fetchone()
    return RunEvent.model_validate({**stored, "seq": row["seq"]})


def list_events(run_id: str, after_seq: int = 0, limit: int = 500) -> list[RunEvent]:
    """Events of one run with ``seq > after_seq`` in order."""
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT seq, body FROM runtime.events WHERE run_id = %s AND seq > %s ORDER BY seq LIMIT %s",
            (run_id, after_seq, limit),
        ).fetchall()
    return [RunEvent.model_validate({**r["body"], "seq": r["seq"]}) for r in rows]
