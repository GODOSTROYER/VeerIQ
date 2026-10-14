"""Read-side queries for the RewindSafe workflow.

Pure reads over ``app`` / ``authority`` / ``recovery`` plus the derived views the
API and agent tools need: order assessment (damaged / healthy / changed after
snapshot / deleted / on hold), protected-state checks, ``app_state`` and
``snapshot_diff``. Core functions take an explicit psycopg connection; the
module-level wrappers at the bottom borrow one from the runtime pool.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

from rewindsafe.contracts import InvariantCheck, InvariantStatus
from rewindsafe.workflows.rewindsafe import fixture as fx
from rewindsafe.workflows.rewindsafe.fixture import iso

ORDER_COLUMNS = (
    "order_id, tenant_id, customer_id, status, total_cents, currency, shipping_region, item_summary, "
    "owner_account, row_version, updated_at, updated_by"
)


def cursor(conn: psycopg.Connection) -> psycopg.Cursor[dict[str, Any]]:
    """A dict-row cursor regardless of the connection's default row factory."""
    return conn.cursor(row_factory=dict_row)


# ─── primitive reads ───────────────────────────────────────────────────────


def get_generation(conn: psycopg.Connection) -> int:
    row = cursor(conn).execute("SELECT generation FROM runtime.fixture_state WHERE id = 1").fetchone()
    if row is None:
        raise RuntimeError("fixture has not been initialised (runtime.fixture_state is empty)")
    return int(row["generation"])


def get_epoch(conn: psycopg.Connection, tenant_id: str) -> int:
    row = cursor(conn).execute(
        "SELECT epoch FROM authority.tenant_epochs WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"unknown tenant {tenant_id!r}")
    return int(row["epoch"])


def load_snapshot(conn: psycopg.Connection, snapshot_id: str) -> dict[str, Any] | None:
    return cursor(conn).execute(
        "SELECT snapshot_id, taken_at, description, content, content_digest, approved, approved_by, approved_at "
        "FROM recovery.snapshots WHERE snapshot_id = %s",
        (snapshot_id,),
    ).fetchone()


def load_annotations(conn: psycopg.Connection, snapshot_id: str) -> list[dict[str, Any]]:
    return cursor(conn).execute(
        "SELECT annotation_id, author, created_at, body, trust FROM recovery.annotations "
        "WHERE snapshot_id = %s ORDER BY created_at, annotation_id",
        (snapshot_id,),
    ).fetchall()


def snapshot_orders_by_id(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {o["order_id"]: o for o in snapshot["content"]["orders"]}


def snapshot_customers_by_id(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["customer_id"]: c for c in snapshot["content"]["customers"]}


def fetch_orders(conn: psycopg.Connection, order_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    ids = list(order_ids)
    if not ids:
        return {}
    rows = cursor(conn).execute(
        f"SELECT {ORDER_COLUMNS} FROM app.orders WHERE order_id = ANY(%s)", (ids,)
    ).fetchall()
    return {r["order_id"]: r for r in rows}


def fetch_tombstones(conn: psycopg.Connection, tenant_id: str) -> dict[tuple[str, str], dict[str, Any]]:
    rows = cursor(conn).execute(
        "SELECT tenant_id, entity_type, entity_id, display_name, deleted_at, reason, deleted_by "
        "FROM authority.tombstones WHERE tenant_id = %s",
        (tenant_id,),
    ).fetchall()
    return {(r["entity_type"], r["entity_id"]): r for r in rows}


def fetch_active_holds(conn: psycopg.Connection, tenant_id: str) -> dict[tuple[str, str], dict[str, Any]]:
    rows = cursor(conn).execute(
        "SELECT hold_id, tenant_id, entity_type, entity_id, reason, placed_by, placed_at FROM authority.record_holds "
        "WHERE tenant_id = %s AND active ORDER BY placed_at, hold_id",
        (tenant_id,),
    ).fetchall()
    return {(r["entity_type"], r["entity_id"]): r for r in rows}


def snapshot_order_tenant(conn: psycopg.Connection, order_id: str) -> str | None:
    """Tenant that owns ``order_id`` according to the approved snapshots, falling back to live data."""
    cur = cursor(conn)
    row = cur.execute(
        "SELECT o->>'tenant_id' AS tenant_id FROM recovery.snapshots s, "
        "jsonb_array_elements(s.content->'orders') o WHERE o->>'order_id' = %s LIMIT 1",
        (order_id,),
    ).fetchone()
    if row:
        return row["tenant_id"]
    row = cur.execute("SELECT tenant_id FROM app.orders WHERE order_id = %s", (order_id,)).fetchone()
    return row["tenant_id"] if row else None


# ─── assessment ────────────────────────────────────────────────────────────

CONDITIONS = ("damaged", "healthy", "changed_after_snapshot", "deleted_tombstoned", "on_hold")


def _snap_view(row: dict[str, Any]) -> dict[str, Any]:
    return {f: row.get(f) for f in fx.REPAIRABLE_FIELDS}


def _cur_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    view = {f: row.get(f) for f in fx.REPAIRABLE_FIELDS}
    view["row_version"] = int(row["row_version"])
    view["updated_by"] = row["updated_by"]
    view["updated_at"] = iso(row["updated_at"])
    return view


@dataclass
class OrderAssessment:
    order_id: str
    tenant_id: str
    customer_id: str
    condition: str
    differing_fields: list[str]
    snapshot_row: dict[str, Any]
    current_row: dict[str, Any] | None
    tombstone: dict[str, Any] | None = None
    hold: dict[str, Any] | None = None
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_comparison(self) -> dict[str, Any]:
        """Shape returned by ``compare_current`` and ``/app/snapshot-diff`` rows."""
        return {
            "order_id": self.order_id,
            "condition": self.condition,
            "snapshot": _snap_view(self.snapshot_row),
            "current": _cur_view(self.current_row),
            "differing_fields": list(self.differing_fields),
            "notes": self.notes,
        }


def assess_orders(
    conn: psycopg.Connection,
    tenant_id: str,
    order_ids: Iterable[str],
    snapshot: dict[str, Any],
) -> dict[str, OrderAssessment]:
    """Classify each order against the snapshot. Order ids absent from the snapshot are skipped."""
    ids = list(dict.fromkeys(order_ids))
    snap_orders = snapshot_orders_by_id(snapshot)
    current = fetch_orders(conn, ids)
    tombs = fetch_tombstones(conn, tenant_id)
    holds = fetch_active_holds(conn, tenant_id)

    out: dict[str, OrderAssessment] = {}
    for oid in ids:
        snap_row = snap_orders.get(oid)
        if snap_row is None or snap_row["tenant_id"] != tenant_id:
            continue
        cur_row = current.get(oid)
        cust = snap_row["customer_id"]
        tomb = tombs.get(("order", oid)) or tombs.get(("customer", cust))
        hold = holds.get(("order", oid)) or holds.get(("customer", cust))
        diffs = (
            [f for f in fx.REPAIRABLE_FIELDS if cur_row.get(f) != snap_row.get(f)] if cur_row is not None else []
        )

        if tomb is not None:
            condition = "deleted_tombstoned"
            notes = (
                f"Deleted on {iso(tomb['deleted_at'])} ({tomb['reason']}); the deletion is a current decision "
                "and must not be reversed from the snapshot."
            )
        elif hold is not None:
            condition = "on_hold"
            notes = f"Active hold {hold['hold_id']} placed by {hold['placed_by']}: {hold['reason']}."
        elif cur_row is None:
            condition = "changed_after_snapshot"
            notes = "The row no longer exists and there is no recorded tombstone; it was removed after the snapshot."
        elif not diffs:
            condition = "healthy"
            notes = "Matches the approved snapshot on every repairable field."
        elif cur_row["updated_by"] == fx.INCIDENT_WRITER:
            condition = "damaged"
            notes = (
                f"Last written by {fx.INCIDENT_WRITER} ({iso(cur_row['updated_at'])}); "
                f"differs from the snapshot on: {', '.join(diffs)}."
            )
        else:
            condition = "changed_after_snapshot"
            notes = (
                f"Updated after the snapshot by {cur_row['updated_by']} ({iso(cur_row['updated_at'])}); "
                "this is a legitimate later change and must not be overwritten."
            )
        out[oid] = OrderAssessment(
            order_id=oid,
            tenant_id=tenant_id,
            customer_id=cust,
            condition=condition,
            differing_fields=diffs,
            snapshot_row=snap_row,
            current_row=cur_row,
            tombstone=tomb,
            hold=hold,
            notes=notes,
        )
    return out


# ─── protected checks ──────────────────────────────────────────────────────


def protected_check_list(conn: psycopg.Connection, tenant_id: str) -> list[InvariantCheck]:
    """Protected-state checks for the Atlas tenant (empty for any other tenant)."""
    if tenant_id != fx.TENANT_ATLAS:
        return []
    cur = cursor(conn)
    snapshot = load_snapshot(conn, fx.SNAPSHOT_ID)
    if snapshot is None:
        raise RuntimeError("approved snapshot is missing; fixture not initialised")
    snap_orders = snapshot_orders_by_id(snapshot)
    checks: list[InvariantCheck] = []

    current = fetch_orders(conn, ["O-2041", "O-2042", "O-2046", "O-2043", "O-2044"])

    for oid in ("O-2041", "O-2042", "O-2046"):
        row = current.get(oid)
        snap_row = snap_orders[oid]
        repaired = row is not None and all(row[f] == snap_row[f] for f in fx.REPAIRABLE_FIELDS)
        checks.append(
            InvariantCheck(
                check_id=f"repair:{oid}",
                label=f"Order {oid} repaired to its snapshot values",
                category="repair",
                status=InvariantStatus.REPAIRED if repaired else InvariantStatus.PENDING,
                detail=(
                    "Current values equal the approved snapshot."
                    if repaired
                    else "Current values still differ from the approved snapshot."
                ),
                evidence={
                    "current": _cur_view(row),
                    "snapshot": _snap_view(snap_row),
                },
            )
        )

    cust_gone = (
        cur.execute("SELECT 1 FROM app.customers WHERE customer_id = 'C-1003'").fetchone() is None
        and cur.execute(
            "SELECT 1 FROM authority.tombstones WHERE tenant_id = %s AND entity_type = 'customer' "
            "AND entity_id = 'C-1003'",
            (tenant_id,),
        ).fetchone()
        is not None
    )
    checks.append(
        InvariantCheck(
            check_id="tombstone:C-1003",
            label="Deleted customer Orion Freight stays deleted",
            category="tombstone",
            status=InvariantStatus.PRESERVED if cust_gone else InvariantStatus.VIOLATED,
            detail="Customer C-1003 is absent and its tombstone is intact."
            if cust_gone
            else "Customer C-1003 exists again or its tombstone is gone.",
            evidence={"erasure_request": "ER-889"},
        )
    )
    order_gone = (
        "O-2044" not in current
        and cur.execute(
            "SELECT 1 FROM authority.tombstones WHERE tenant_id = %s AND entity_type = 'order' "
            "AND entity_id = 'O-2044'",
            (tenant_id,),
        ).fetchone()
        is not None
    )
    checks.append(
        InvariantCheck(
            check_id="tombstone:O-2044",
            label="Order O-2044 is not resurrected",
            category="tombstone",
            status=InvariantStatus.PRESERVED if order_gone else InvariantStatus.VIOLATED,
            detail="Order O-2044 is absent and its tombstone is intact."
            if order_gone
            else "Order O-2044 exists again or its tombstone is gone.",
        )
    )

    ag = cur.execute(
        "SELECT status, revoked_at FROM authority.access_grants WHERE grant_id = 'AG-77' AND tenant_id = %s",
        (tenant_id,),
    ).fetchone()
    revoked = ag is not None and ag["status"] == "revoked"
    checks.append(
        InvariantCheck(
            check_id="access:AG-77",
            label="Revoked svc-legacy-sync stays revoked",
            category="access",
            status=InvariantStatus.PRESERVED if revoked else InvariantStatus.VIOLATED,
            detail="Access grant AG-77 is still revoked." if revoked else "Access grant AG-77 is active again.",
            evidence={"status": ag["status"] if ag else None},
        )
    )

    later = current.get("O-2043")
    later_ok = (
        later is not None
        and later["status"] == "shipped"
        and later["updated_by"] == fx.FULFILLMENT_WRITER
        and int(later["row_version"]) == 2
    )
    checks.append(
        InvariantCheck(
            check_id="later_update:O-2043",
            label="Fulfillment's later 'shipped' update survives",
            category="later_update",
            status=InvariantStatus.PRESERVED if later_ok else InvariantStatus.VIOLATED,
            detail="Order O-2043 still shows the later fulfillment update."
            if later_ok
            else "Order O-2043 was changed after fulfillment's update.",
            evidence={"current": _cur_view(later)},
        )
    )

    actual = fx.beacon_checksum(conn)
    expected = fx.expected_beacon_checksum()
    checks.append(
        InvariantCheck(
            check_id="tenant:beacon",
            label="Beacon tenant untouched",
            category="tenant_isolation",
            status=InvariantStatus.PRESERVED if actual == expected else InvariantStatus.VIOLATED,
            detail="Beacon data checksum matches the fixture."
            if actual == expected
            else "Beacon data no longer matches its fixture checksum.",
            evidence={"checksum": actual, "expected_checksum": expected},
        )
    )
    return checks


# ─── API views ─────────────────────────────────────────────────────────────


def snapshot_diff_conn(conn: psycopg.Connection, tenant_id: str) -> list[dict[str, Any]]:
    """Per-order snapshot-vs-current rows for a tenant (Atlas includes the deleted O-2044)."""
    snapshot = load_snapshot(conn, fx.SNAPSHOT_ID)
    if snapshot is None:
        return []
    snap_orders = [o for o in snapshot["content"]["orders"] if o["tenant_id"] == tenant_id]
    customers = snapshot_customers_by_id(snapshot)
    assessed = assess_orders(conn, tenant_id, [o["order_id"] for o in snap_orders], snapshot)
    rows = []
    for o in snap_orders:
        a = assessed[o["order_id"]]
        comp = a.as_comparison()
        comp["customer_name"] = customers.get(o["customer_id"], {}).get("name", o["customer_id"])
        comp["customer_id"] = o["customer_id"]
        rows.append(comp)
    return rows


def fixture_status_conn(conn: psycopg.Connection) -> dict[str, Any]:
    """Whether the shared demo fixture has been changed since its last reset.

    ``repaired_orders`` are orders that a committed receipt in the current generation already
    repaired; the fixture is also dirty if a record hold was placed or an authority epoch bumped.
    """
    cur = cursor(conn)
    generation = get_generation(conn)
    repaired: list[str] = []
    for r in cur.execute(
        "SELECT body FROM runtime.receipts WHERE fixture_generation = %s AND result = 'committed' ORDER BY created_at",
        (generation,),
    ).fetchall():
        for c in (r["body"] or {}).get("changes", []):
            rid = c.get("row_id")
            if rid and rid not in repaired:
                repaired.append(rid)
    holds = int(cur.execute("SELECT count(*) AS n FROM authority.record_holds WHERE active").fetchone()["n"])  # type: ignore[index]
    epoch_bumped = bool(cur.execute("SELECT 1 FROM authority.tenant_epochs WHERE epoch > 1 LIMIT 1").fetchone())
    dirty = bool(repaired) or holds > 0 or epoch_bumped
    if repaired:
        note = f"Already repaired in this generation: {', '.join(repaired)}. Reset to rerun a scenario from the incident state."
    elif dirty:
        note = "Authority state changed since the last reset (a hold or epoch bump). Reset to restore the incident state."
    else:
        note = "Fixture is in its original incident state."
    return {"generation": generation, "dirty": dirty, "repaired_orders": repaired, "note": note}


def fixture_status() -> dict[str, Any]:
    from rewindsafe.runtime import db

    with db.connection() as conn, conn.transaction():
        st = fixture_status_conn(conn)
    return {"dirty": st["dirty"], "repaired_orders": st["repaired_orders"], "note": st["note"]}


def app_state_conn(conn: psycopg.Connection, tenant_id: str) -> dict[str, Any]:
    """Payload for ``GET /api/app/state`` (see architecture.md section 8)."""
    cur = cursor(conn)
    tenant = cur.execute("SELECT tenant_id, name FROM app.tenants WHERE tenant_id = %s", (tenant_id,)).fetchone()
    if tenant is None:
        raise LookupError(f"unknown tenant {tenant_id!r}")
    snapshot = load_snapshot(conn, fx.SNAPSHOT_ID)
    snap_customers = snapshot_customers_by_id(snapshot) if snapshot else {}
    holds = fetch_active_holds(conn, tenant_id)
    tombs = fetch_tombstones(conn, tenant_id)

    customers = {
        r["customer_id"]: r["name"]
        for r in cur.execute("SELECT customer_id, name FROM app.customers WHERE tenant_id = %s", (tenant_id,))
    }
    order_rows = cur.execute(
        f"SELECT {ORDER_COLUMNS} FROM app.orders WHERE tenant_id = %s ORDER BY order_id", (tenant_id,)
    ).fetchall()
    assessed = (
        assess_orders(conn, tenant_id, [r["order_id"] for r in order_rows], snapshot) if snapshot else {}
    )
    orders = []
    for r in order_rows:
        a = assessed.get(r["order_id"])
        hold = holds.get(("order", r["order_id"]))
        orders.append(
            {
                "order_id": r["order_id"],
                "customer_id": r["customer_id"],
                "customer_name": customers.get(r["customer_id"])
                or snap_customers.get(r["customer_id"], {}).get("name", r["customer_id"]),
                "status": r["status"],
                "total_cents": int(r["total_cents"]),
                "currency": r["currency"],
                "shipping_region": r["shipping_region"],
                "item_summary": r["item_summary"],
                "owner_account": r["owner_account"],
                "row_version": int(r["row_version"]),
                "updated_at": iso(r["updated_at"]),
                "updated_by": r["updated_by"],
                "condition": a.condition if a else None,
                "on_hold": hold is not None,
                "hold_reason": hold["reason"] if hold else None,
            }
        )

    deleted = [
        {
            "entity_type": t["entity_type"],
            "entity_id": t["entity_id"],
            "display_name": t["display_name"],
            "deleted_at": iso(t["deleted_at"]),
            "reason": t["reason"],
            "deleted_by": t["deleted_by"],
        }
        for t in sorted(tombs.values(), key=lambda t: (t["deleted_at"], t["entity_type"], t["entity_id"]))
    ]
    access_grants = [
        {
            "grant_id": g["grant_id"],
            "principal": g["principal"],
            "scope": g["scope"],
            "status": g["status"],
            "revoked_at": iso(g["revoked_at"]),
            "revoked_reason": g["revoked_reason"],
        }
        for g in cur.execute(
            "SELECT grant_id, principal, scope, status, revoked_at, revoked_reason "
            "FROM authority.access_grants WHERE tenant_id = %s ORDER BY grant_id",
            (tenant_id,),
        )
    ]
    hold_list = [
        {
            "hold_id": h["hold_id"],
            "entity_type": h["entity_type"],
            "entity_id": h["entity_id"],
            "reason": h["reason"],
            "placed_by": h["placed_by"],
            "placed_at": iso(h["placed_at"]),
        }
        for h in holds.values()
    ]

    incident_row = cur.execute(
        "SELECT incident_id, tenant_ids, title, description, started_at, detected_at, affected "
        "FROM app.incidents WHERE %s = ANY(tenant_ids) ORDER BY started_at DESC LIMIT 1",
        (tenant_id,),
    ).fetchone()
    incident = None
    if incident_row:
        incident = {
            "incident_id": incident_row["incident_id"],
            "title": incident_row["title"],
            "description": incident_row["description"],
            "started_at": iso(incident_row["started_at"]),
            "detected_at": iso(incident_row["detected_at"]),
            "tenant_id": tenant_id,
            "other_tenants_affected": any(t != tenant_id for t in incident_row["tenant_ids"]),
            "affected": [a for a in incident_row["affected"] if a["tenant_id"] == tenant_id],
        }

    actual = fx.beacon_checksum(conn)
    expected = fx.expected_beacon_checksum()
    annotations = [
        {
            "annotation_id": a["annotation_id"],
            "author": a["author"],
            "created_at": iso(a["created_at"]),
            "body": a["body"],
            "trust": "untrusted",
        }
        for a in (load_annotations(conn, snapshot["snapshot_id"]) if snapshot else [])
    ]
    fixture_state = fixture_status_conn(conn)
    return {
        "tenant": {"id": tenant["tenant_id"], "name": tenant["name"]},
        "orders": orders,
        "deleted": deleted,
        "access_grants": access_grants,
        "holds": hold_list,
        "snapshot": (
            {
                "snapshot_id": snapshot["snapshot_id"],
                "taken_at": iso(snapshot["taken_at"]),
                "description": snapshot["description"],
                "content_digest": snapshot["content_digest"],
                "approved_by": snapshot["approved_by"],
                "approved_at": iso(snapshot["approved_at"]),
                "annotations": annotations,
            }
            if snapshot
            else None
        ),
        "incident": incident,
        "beacon": {
            "checksum": actual,
            "expected_checksum": expected,
            "untouched": actual == expected,
            "order_count": fx.beacon_order_count(conn),
        },
        "fixture_generation": get_generation(conn),
        "fixture": fixture_state,
    }


# ─── pooled wrappers (borrow a connection from the runtime) ────────────────


def app_state(tenant_id: str) -> dict[str, Any]:
    from rewindsafe.runtime import db

    with db.connection() as conn, conn.transaction():
        return app_state_conn(conn, tenant_id)


def snapshot_diff(tenant_id: str) -> list[dict[str, Any]]:
    from rewindsafe.runtime import db

    with db.connection() as conn, conn.transaction():
        return snapshot_diff_conn(conn, tenant_id)


def protected_checks(tenant_id: str) -> list[InvariantCheck]:
    from rewindsafe.runtime import db

    with db.connection() as conn, conn.transaction():
        return protected_check_list(conn, tenant_id)
