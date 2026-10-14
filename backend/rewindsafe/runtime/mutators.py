"""Mutator handler entry log (architecture.md 4.6).

Every MUTATE/ADMIN handler calls :func:`record_entry` as its FIRST statement,
on a separate autocommit connection. Zero rows for ``(run_id, handler)`` is the
proof that a prohibited handler was never entered.
"""

from __future__ import annotations

from rewindsafe.runtime import db


def record_entry(handler: str, *, run_id: str | None, proposal_id: str | None, via: str) -> None:
    """``via`` is one of ``dispatcher`` | ``operator_admin`` | ``test``."""
    with db.autocommit_connection() as conn:
        conn.execute(
            "INSERT INTO runtime.mutator_entries (run_id, proposal_id, handler, via) VALUES (%s, %s, %s, %s)",
            (run_id, proposal_id, handler, via),
        )


def count_entries(handler: str, *, run_id: str | None = None) -> int:
    with db.connection() as conn:
        if run_id is None:
            row = conn.execute(
                "SELECT count(*) AS n FROM runtime.mutator_entries WHERE handler = %s", (handler,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT count(*) AS n FROM runtime.mutator_entries WHERE handler = %s AND run_id = %s",
                (handler, run_id),
            ).fetchone()
    return int(row["n"])
