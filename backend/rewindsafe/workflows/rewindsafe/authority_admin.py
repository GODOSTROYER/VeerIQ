"""Authority administration: the only code that changes current decisions (holds, tombstones, access).

This is the privileged, operator-only path. It is never in an agent grant or a
signed recovery plan; ``restore_access_grant`` is reachable by an agent only
through the dispatcher (where it is expected to be refused) and by an operator
through the positive-control route.

Lock protocol (matches ``executor`` lock order): ``runtime.fixture_state`` FOR SHARE,
then the tenant's ``authority.tenant_epochs`` row FOR UPDATE, then mutate under
``SET LOCAL ROLE rs_authority_admin`` and bump the epoch by one. Taking the epoch row
exclusively serializes authority changes with each other and with the executor's
FOR SHARE epoch check, so a repair can never commit on an epoch that has moved.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from rewindsafe.runtime.canonical import utcnow
from rewindsafe.workflows.rewindsafe import queries as q

RESTORE_HANDLER = "restore_access_grant"


class AuthorityAdminError(ValueError):
    """The requested authority change is invalid (unknown target, already in that state...)."""


def _begin_change(conn: psycopg.Connection, tenant_id: str) -> int:
    """Take the documented locks and return the current epoch. Must run inside a transaction."""
    cur = q.cursor(conn)
    cur.execute("SELECT generation FROM runtime.fixture_state WHERE id = 1 FOR SHARE")
    row = cur.execute(
        "SELECT epoch FROM authority.tenant_epochs WHERE tenant_id = %s FOR UPDATE", (tenant_id,)
    ).fetchone()
    if row is None:
        raise AuthorityAdminError(f"unknown tenant {tenant_id!r}")
    return int(row["epoch"])


def _bump_epoch(conn: psycopg.Connection, tenant_id: str) -> int:
    row = q.cursor(conn).execute(
        "UPDATE authority.tenant_epochs SET epoch = epoch + 1, updated_at = %s WHERE tenant_id = %s RETURNING epoch",
        (utcnow(), tenant_id),
    ).fetchone()
    return int(row["epoch"])  # type: ignore[index]


def _result(kind: str, tenant_id: str, before: int, after: int, **fields: Any) -> dict[str, Any]:
    return {"ok": True, "change": kind, "tenant_id": tenant_id, "epoch_before": before, "epoch_after": after, **fields}


# ─── core (explicit connection, idle or inside a transaction) ──────────────


def restore_access_grant_tx(conn: psycopg.Connection, tenant_id: str, grant_id: str, reason: str) -> dict[str, Any]:
    """Flip a revoked access grant back to active and bump the tenant epoch."""
    cur = q.cursor(conn)
    with conn.transaction():
        before = _begin_change(conn, tenant_id)
        row = cur.execute(
            "SELECT status FROM authority.access_grants WHERE grant_id = %s AND tenant_id = %s FOR UPDATE",
            (grant_id, tenant_id),
        ).fetchone()
        if row is None:
            raise AuthorityAdminError(f"access grant {grant_id!r} does not exist in tenant {tenant_id!r}")
        status_before = row["status"]
        cur.execute("SET LOCAL ROLE rs_authority_admin")
        cur.execute(
            "UPDATE authority.access_grants SET status = 'active', revoked_at = NULL, revoked_by = NULL, "
            "revoked_reason = NULL, row_version = row_version + 1, updated_at = %s WHERE grant_id = %s",
            (utcnow(), grant_id),
        )
        after = _bump_epoch(conn, tenant_id)
        cur.execute("RESET ROLE")
    return _result(
        "restore_access_grant", tenant_id, before, after,
        grant_id=grant_id, status_before=status_before, status_after="active", reason=reason,
    )


def revoke_access_tx(
    conn: psycopg.Connection, tenant_id: str, grant_id: str, reason: str, revoked_by: str
) -> dict[str, Any]:
    cur = q.cursor(conn)
    with conn.transaction():
        before = _begin_change(conn, tenant_id)
        row = cur.execute(
            "SELECT status FROM authority.access_grants WHERE grant_id = %s AND tenant_id = %s FOR UPDATE",
            (grant_id, tenant_id),
        ).fetchone()
        if row is None:
            raise AuthorityAdminError(f"access grant {grant_id!r} does not exist in tenant {tenant_id!r}")
        status_before = row["status"]
        cur.execute("SET LOCAL ROLE rs_authority_admin")
        cur.execute(
            "UPDATE authority.access_grants SET status = 'revoked', revoked_at = %s, revoked_by = %s, "
            "revoked_reason = %s, row_version = row_version + 1, updated_at = %s WHERE grant_id = %s",
            (utcnow(), revoked_by, reason, utcnow(), grant_id),
        )
        after = _bump_epoch(conn, tenant_id)
        cur.execute("RESET ROLE")
    return _result(
        "revoke_access", tenant_id, before, after,
        grant_id=grant_id, status_before=status_before, status_after="revoked", reason=reason,
    )


def place_hold_tx(
    conn: psycopg.Connection, tenant_id: str, entity_type: str, entity_id: str, reason: str, placed_by: str
) -> dict[str, Any]:
    if entity_type not in ("order", "customer"):
        raise AuthorityAdminError(f"cannot hold entity type {entity_type!r}")
    cur = q.cursor(conn)
    with conn.transaction():
        before = _begin_change(conn, tenant_id)
        table, col = ("app.orders", "order_id") if entity_type == "order" else ("app.customers", "customer_id")
        exists = cur.execute(
            f"SELECT 1 FROM {table} WHERE {col} = %s AND tenant_id = %s", (entity_id, tenant_id)
        ).fetchone()
        if exists is None:
            raise AuthorityAdminError(f"{entity_type} {entity_id!r} does not exist in tenant {tenant_id!r}")
        hold_id = f"HLD-{uuid.uuid4().hex[:6].upper()}"
        cur.execute("SET LOCAL ROLE rs_authority_admin")
        cur.execute(
            "INSERT INTO authority.record_holds (hold_id, tenant_id, entity_type, entity_id, reason, placed_by, placed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (hold_id, tenant_id, entity_type, entity_id, reason, placed_by, utcnow()),
        )
        after = _bump_epoch(conn, tenant_id)
        cur.execute("RESET ROLE")
    return _result(
        "place_hold", tenant_id, before, after,
        hold_id=hold_id, entity_type=entity_type, entity_id=entity_id, reason=reason, placed_by=placed_by,
    )


def add_tombstone_tx(
    conn: psycopg.Connection,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    display_name: str,
    reason: str,
    deleted_by: str,
) -> dict[str, Any]:
    """Record a deletion decision. (Removing the application row itself is the application's business.)"""
    if entity_type not in ("order", "customer"):
        raise AuthorityAdminError(f"cannot tombstone entity type {entity_type!r}")
    cur = q.cursor(conn)
    with conn.transaction():
        before = _begin_change(conn, tenant_id)
        if cur.execute(
            "SELECT 1 FROM authority.tombstones WHERE tenant_id = %s AND entity_type = %s AND entity_id = %s",
            (tenant_id, entity_type, entity_id),
        ).fetchone():
            raise AuthorityAdminError(f"{entity_type} {entity_id!r} is already tombstoned")
        cur.execute("SET LOCAL ROLE rs_authority_admin")
        cur.execute(
            "INSERT INTO authority.tombstones (tenant_id, entity_type, entity_id, display_name, deleted_at, reason, "
            "deleted_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (tenant_id, entity_type, entity_id, display_name, utcnow(), reason, deleted_by),
        )
        after = _bump_epoch(conn, tenant_id)
        cur.execute("RESET ROLE")
    return _result(
        "add_tombstone", tenant_id, before, after,
        entity_type=entity_type, entity_id=entity_id, reason=reason, deleted_by=deleted_by,
    )


# ─── public API (borrows its own autocommit connection from the runtime) ───


def restore_access_grant(
    tenant_id: str, grant_id: str, reason: str, *, run_id: str | None, proposal_id: str | None, via: str
) -> dict[str, Any]:
    """The real privileged handler. Records a mutator entry as its FIRST statement."""
    from rewindsafe.runtime import db, mutators

    mutators.record_entry(RESTORE_HANDLER, run_id=run_id, proposal_id=proposal_id, via=via)
    with db.autocommit_connection() as conn:
        return restore_access_grant_tx(conn, tenant_id, grant_id, reason)


def place_hold(tenant_id: str, entity_type: str, entity_id: str, reason: str, placed_by: str) -> dict[str, Any]:
    from rewindsafe.runtime import db

    with db.autocommit_connection() as conn:
        return place_hold_tx(conn, tenant_id, entity_type, entity_id, reason, placed_by)


def add_tombstone(
    tenant_id: str, entity_type: str, entity_id: str, display_name: str, reason: str, deleted_by: str
) -> dict[str, Any]:
    from rewindsafe.runtime import db

    with db.autocommit_connection() as conn:
        return add_tombstone_tx(conn, tenant_id, entity_type, entity_id, display_name, reason, deleted_by)


def revoke_access(tenant_id: str, grant_id: str, reason: str, revoked_by: str) -> dict[str, Any]:
    from rewindsafe.runtime import db

    with db.autocommit_connection() as conn:
        return revoke_access_tx(conn, tenant_id, grant_id, reason, revoked_by)
