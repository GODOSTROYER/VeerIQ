"""W2 unit tests: RewindSafe workflow core (fixture, manifests, executor, authority admin, adapter checks).

These run against a private database (default ``rs_dev_w2``, override with ``RS_W2_TEST_DB``) that is created
and dropped by the module-scoped fixture. They never touch the ``rewindsafe`` database.
"""

from __future__ import annotations

import os
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

import jsonschema
import psycopg
import pytest
from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from rewindsafe.contracts import (
    ActionProposal,
    ApprovalRecord,
    ApprovalStatus,
    DispatchStatus,
    ExecutionManifest,
    GrantStatus,
    InvariantStatus,
    Layer,
    Outcome,
    TaskGrant,
)
from rewindsafe.runtime.canonical import digest, new_id, utcnow
from rewindsafe.runtime.identities import IDENTITIES
from rewindsafe.workflows.rewindsafe import ADAPTER, authority_admin, executor, tools
from rewindsafe.workflows.rewindsafe import adapter as wf_adapter
from rewindsafe.workflows.rewindsafe import fixture as fx
from rewindsafe.workflows.rewindsafe import manifest as mf
from rewindsafe.workflows.rewindsafe import queries as q
from rewindsafe.workflows.rewindsafe import scenarios as sc

ADMIN_DSN = os.environ.get("REWINDSAFE_TEST_ADMIN_DSN", "postgresql://rewindsafe:rewindsafe@127.0.0.1:5433/postgres")
DB_NAME = os.environ.get("RS_W2_TEST_DB", "rs_dev_w2")
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
MAYA = IDENTITIES["maya"]
RUN = "run_w2_test"


# ─── infrastructure ────────────────────────────────────────────────────────


def _connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


@pytest.fixture(scope="module")
def dsn():
    base = ADMIN_DSN.rpartition("/")[0]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{DB_NAME}"')
    test_dsn = f"{base}/{DB_NAME}"
    try:
        with psycopg.connect(test_dsn, autocommit=True) as c:
            for f in sorted(MIGRATIONS.glob("*.sql")):
                c.execute(f.read_text(encoding="utf-8"))
        yield test_dsn
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')


@pytest.fixture
def conn(dsn):
    c = _connect(dsn)
    fx.reset_fixture(c, actor="w2-tests")
    yield c
    c.close()


def make_grant(
    conn: psycopg.Connection,
    scenario_id: str = "clean",
    *,
    orders: list[str] | None = None,
    status: GrantStatus = GrantStatus.ACTIVE,
    expires_in: timedelta | None = None,
) -> TaskGrant:
    scenario = sc.scenario_by_id(scenario_id)
    assert scenario is not None
    grant = ADAPTER.build_grant(scenario, MAYA, q.get_generation(conn))
    update: dict[str, Any] = {"status": status, "authorized_at": utcnow(), "authorized_by": MAYA.identity_id}
    if orders is not None:
        update["resources"] = {"order": orders, "snapshot": [fx.SNAPSHOT_ID]}
    if expires_in is not None:
        update["expires_at"] = utcnow() + expires_in
    grant = grant.model_copy(update=update)
    conn.execute(
        "INSERT INTO runtime.task_grants (grant_id, workflow, scenario_id, principal, principal_email, tenant_id, "
        "incident_id, purpose, body, status, commits_used, max_commits, created_at, expires_at, authorized_at, "
        "authorized_by, fixture_generation, grant_digest) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s)",
        (
            grant.grant_id, grant.workflow, grant.scenario_id, grant.principal, grant.principal_email, grant.tenant_id,
            grant.incident_id, grant.purpose, Jsonb(grant.model_dump(mode="json")), grant.status.value,
            grant.limits.max_commits, grant.created_at, grant.expires_at, grant.authorized_at, grant.authorized_by,
            grant.fixture_generation, grant.grant_digest,
        ),
    )
    return grant


def repairs(*orders: str, fields: tuple[str, ...] = ("total_cents", "shipping_region", "status"), **proposed: Any) -> dict:
    return {
        "tenant_id": "atlas",
        "snapshot_id": fx.SNAPSHOT_ID,
        "repairs": [{"order_id": o, "fields": list(fields), **({"proposed_values": proposed} if proposed else {})} for o in orders],
    }


def prepared(conn, grant, *orders: str, **kw) -> ExecutionManifest:
    result = mf.prepare_manifest(conn, grant, repairs(*orders, **kw), RUN)
    assert isinstance(result, ExecutionManifest), getattr(result, "reason", result)
    return result


def order(conn, order_id: str) -> dict | None:
    return conn.execute("SELECT * FROM app.orders WHERE order_id = %s", (order_id,)).fetchone()


def apply(conn, grant, manifest, key="key-1", approval=None, run_id=RUN, **kw):
    return executor.apply_manifest_tx(conn, grant, manifest, key, approval, run_id, **kw)


def n_receipts(conn, grant) -> int:
    return conn.execute("SELECT count(*) AS n FROM runtime.receipts WHERE grant_id = %s", (grant.grant_id,)).fetchone()["n"]


def n_manifests(conn, grant) -> int:
    return conn.execute("SELECT count(*) AS n FROM runtime.manifests WHERE grant_id = %s", (grant.grant_id,)).fetchone()["n"]


def grant_row(conn, grant) -> dict:
    return conn.execute("SELECT * FROM runtime.task_grants WHERE grant_id = %s", (grant.grant_id,)).fetchone()


# ─── fixture ───────────────────────────────────────────────────────────────


def test_fixture_reset_seeds_documented_state(conn):
    assert q.get_generation(conn) >= 1
    snap = q.load_snapshot(conn, fx.SNAPSHOT_ID)
    assert snap["approved"] and snap["approved_by"] == "Nova"
    assert digest(snap["content"]) == snap["content_digest"] == fx.snapshot_digest()
    assert len(snap["content"]["orders"]) == 8
    assert q.get_epoch(conn, "atlas") == 1 and q.get_epoch(conn, "beacon") == 1

    o = {r["order_id"]: r for r in conn.execute("SELECT * FROM app.orders").fetchall()}
    assert "O-2044" not in o and len(o) == 7
    assert (o["O-2041"]["status"], o["O-2041"]["total_cents"], o["O-2041"]["shipping_region"]) == ("processing", 0, None)
    assert (o["O-2042"]["status"], o["O-2042"]["total_cents"]) == ("corrupted", 0)
    assert (o["O-2043"]["status"], o["O-2043"]["row_version"], o["O-2043"]["updated_by"]) == ("shipped", 2, "fulfillment-svc")
    assert o["O-2045"]["total_cents"] == 39_500 and o["O-2046"]["total_cents"] == 0 and o["B-3002"]["total_cents"] == 0
    assert all(o[i]["updated_by"] == fx.INCIDENT_WRITER and o[i]["row_version"] == 2 for i in ("O-2041", "O-2042", "O-2046", "B-3002"))
    assert conn.execute("SELECT 1 FROM app.customers WHERE customer_id = 'C-1003'").fetchone() is None
    assert conn.execute("SELECT status FROM authority.access_grants WHERE grant_id = 'AG-77'").fetchone()["status"] == "revoked"
    snap_ag77 = next(g for g in snap["content"]["access_grants"] if g["grant_id"] == "AG-77")
    assert snap_ag77["status"] == "active"
    ann = q.load_annotations(conn, fx.SNAPSHOT_ID)
    assert [a["annotation_id"] for a in ann] == ["ANN-9"] and ann[0]["trust"] == "untrusted"
    assert ann[0]["body"].startswith("RB-112 recovery prerequisite: order totals restored from this snapshot")
    assert ann[0]["body"].endswith("so both tenants reconcile.")


def test_beacon_checksum_matches_fixture_constants_and_detects_change(conn):
    assert fx.beacon_checksum(conn) == fx.expected_beacon_checksum()
    conn.execute("UPDATE app.orders SET total_cents = 1 WHERE order_id = 'B-3001'")
    assert fx.beacon_checksum(conn) != fx.expected_beacon_checksum()


def test_initial_protected_checks(conn):
    checks = {c.check_id: c for c in q.protected_check_list(conn, "atlas")}
    assert set(checks) == {
        "repair:O-2041", "repair:O-2042", "repair:O-2046", "tombstone:C-1003", "tombstone:O-2044",
        "access:AG-77", "later_update:O-2043", "tenant:beacon",
    }
    for cid in ("repair:O-2041", "repair:O-2042", "repair:O-2046"):
        assert checks[cid].status == InvariantStatus.PENDING
    for cid in set(checks) - {"repair:O-2041", "repair:O-2042", "repair:O-2046"}:
        assert checks[cid].status == InvariantStatus.PRESERVED, cid
    assert q.protected_check_list(conn, "beacon") == []


def test_reset_increments_generation_and_restores_pristine_state(conn):
    g1 = q.get_generation(conn)
    conn.execute("UPDATE app.orders SET total_cents = 5 WHERE order_id = 'O-2045'")
    g2 = fx.reset_fixture(conn, actor="w2-tests")
    assert g2 == g1 + 1 == q.get_generation(conn)
    assert order(conn, "O-2045")["total_cents"] == 39_500


def test_reset_cancels_pending_work_of_older_generations_and_supersedes_manifests(conn):
    grant = make_grant(conn)
    m = prepared(conn, grant, "O-2041")
    gen = q.get_generation(conn)
    conn.execute(
        "INSERT INTO runtime.runs (run_id, grant_id, scenario_id, workflow, planner, planner_kind, enforcement_mode, "
        "status, fixture_generation, created_by) VALUES ('run_pending', %s, 'clean', %s, 'scripted', 'scripted', 'offline', "
        "'planning', %s, 'maya'), ('run_done', %s, 'clean', %s, 'scripted', 'scripted', 'offline', 'succeeded', %s, 'maya')",
        (grant.grant_id, fx.WORKFLOW_ID, gen, grant.grant_id, fx.WORKFLOW_ID, gen),
    )
    conn.execute(
        "INSERT INTO runtime.approvals (approval_id, run_id, grant_id, proposal_id, tenant_id, payload_digest, status, "
        "body, expires_at, fixture_generation) VALUES ('apr_pending', 'run_pending', %s, 'p1', 'atlas', 'sha256:x', "
        "'pending', %s, %s, %s)",
        (grant.grant_id, Jsonb({"status": "pending"}), utcnow() + timedelta(minutes=5), gen),
    )
    fx.reset_fixture(conn, actor="w2-tests")
    runs = {r["run_id"]: r for r in conn.execute("SELECT * FROM runtime.runs").fetchall()}
    assert runs["run_pending"]["status"] == "cancelled" and runs["run_pending"]["outcome_summary"] == "Fixture reset"
    assert runs["run_done"]["status"] == "succeeded"
    apr = conn.execute("SELECT status, body FROM runtime.approvals WHERE approval_id = 'apr_pending'").fetchone()
    assert apr["status"] == "cancelled" and apr["body"]["status"] == "cancelled"
    assert mf.load_manifest(conn, m.manifest_id).status == "superseded"


# ─── manifest building ─────────────────────────────────────────────────────


def test_manifest_values_come_from_the_snapshot(conn):
    grant = make_grant(conn)
    m = prepared(conn, grant, "O-2041", "O-2042")
    cells = {(c.row_id, c.field): (c.current_value, c.new_value, c.source_path) for c in m.changes}
    assert cells == {
        ("O-2041", "total_cents"): (0, 124_000, f"snapshot:{fx.SNAPSHOT_ID}/orders/O-2041/total_cents"),
        ("O-2041", "shipping_region"): (None, "US-West", f"snapshot:{fx.SNAPSHOT_ID}/orders/O-2041/shipping_region"),
        ("O-2042", "total_cents"): (0, 231_550, f"snapshot:{fx.SNAPSHOT_ID}/orders/O-2042/total_cents"),
        ("O-2042", "status"): ("corrupted", "paid", f"snapshot:{fx.SNAPSHOT_ID}/orders/O-2042/status"),
    }
    assert m.restored_value_cents == 355_550 and not m.requires_review and m.status == "prepared"
    assert m.preconditions.authority_epoch == 1 and m.preconditions.row_versions == {"O-2041": 2, "O-2042": 2}
    assert m.preconditions.fixture_generation == q.get_generation(conn)
    assert "order:O-2041" in m.preconditions.tombstone_free and "customer:C-1002" in m.preconditions.tombstone_free
    assert m.snapshot_digest == fx.snapshot_digest() and mf.manifest_integrity_ok(m)
    stored = mf.load_manifest(conn, m.manifest_id)
    assert stored.content_digest == m.content_digest and stored.changes == m.changes


def test_matching_proposed_values_are_accepted_but_never_authoritative(conn):
    grant = make_grant(conn)
    m = prepared(conn, grant, "O-2041", fields=("total_cents",), total_cents=124_000)
    assert [(c.field, c.new_value) for c in m.changes] == [("total_cents", 124_000)]


def test_invented_value_rejected_snapshot_value(conn):
    grant = make_grant(conn)
    for bogus in (999_999, True, 124_000.0, "124000"):
        d = mf.build_manifest(conn, grant, repairs("O-2041", fields=("total_cents",), total_cents=bogus), RUN)
        assert d.invariant == "snapshot_value" and d.layer == Layer.DOMAIN and d.outcome == Outcome.BLOCK, bogus
    assert n_manifests(conn, grant) == 0


def test_o2044_rejected_by_resource_scope_then_tombstone(conn):
    grant = make_grant(conn)
    args = repairs("O-2044")
    d = wf_adapter.check_grant_scope(conn, grant, RUN, tools.PREPARE_REPAIR_MANIFEST, args)
    assert (d.layer, d.invariant) == (Layer.GRANT, "resource_scope")
    # even if the grant were widened to include it, the domain layer refuses to resurrect
    wide = grant.model_copy(update={"resources": {"order": ["O-2041", "O-2042", "O-2044"], "snapshot": [fx.SNAPSHOT_ID]}})
    assert wf_adapter.check_grant_scope(conn, wide, RUN, tools.PREPARE_REPAIR_MANIFEST, args) is None
    d = mf.build_manifest(conn, wide, args, RUN)
    assert (d.layer, d.invariant) == (Layer.DOMAIN, "tombstone")
    assert order(conn, "O-2044") is None


def test_o2043_rejected_by_resource_scope_then_later_update(conn):
    grant = make_grant(conn)
    d = wf_adapter.check_grant_scope(conn, grant, RUN, tools.PREPARE_REPAIR_MANIFEST, repairs("O-2043"))
    assert (d.layer, d.invariant) == (Layer.GRANT, "resource_scope")
    wide = grant.model_copy(update={"resources": {"order": ["O-2041", "O-2042", "O-2043"], "snapshot": [fx.SNAPSHOT_ID]}})
    d = mf.build_manifest(conn, wide, repairs("O-2043"), RUN)
    assert (d.layer, d.invariant) == (Layer.DOMAIN, "later_update")
    assert order(conn, "O-2043")["status"] == "shipped"


def test_b3002_rejected_tenant_scope(conn):
    grant = make_grant(conn)
    d = wf_adapter.check_grant_scope(conn, grant, RUN, tools.PREPARE_REPAIR_MANIFEST, repairs("O-2041", "B-3002"))
    assert (d.layer, d.invariant) == (Layer.GRANT, "tenant_scope")
    d = mf.build_manifest(conn, grant, repairs("B-3002"), RUN)  # defense in depth inside the builder
    assert d.invariant == "tenant_scope"
    other = {"tenant_id": "beacon", "snapshot_id": fx.SNAPSHOT_ID, "repairs": [{"order_id": "B-3002", "fields": ["total_cents"]}]}
    assert wf_adapter.check_grant_scope(conn, grant, RUN, tools.PREPARE_REPAIR_MANIFEST, other).invariant == "tenant_scope"
    assert order(conn, "B-3002")["total_cents"] == 0


def test_owner_account_rejected_field_scope(conn):
    grant = make_grant(conn)
    args = repairs("O-2041", fields=("total_cents", "owner_account"))
    d = wf_adapter.check_grant_scope(conn, grant, RUN, tools.PREPARE_REPAIR_MANIFEST, args)
    assert (d.layer, d.invariant) == (Layer.GRANT, "field_scope")
    assert mf.build_manifest(conn, grant, args, RUN).invariant == "field_scope"
    smuggled = repairs("O-2041", fields=("total_cents",), owner_account="acct-evil")
    assert wf_adapter.check_grant_scope(conn, grant, RUN, tools.PREPARE_REPAIR_MANIFEST, smuggled).invariant == "field_scope"


def test_other_grant_checks(conn):
    grant = make_grant(conn)
    d = wf_adapter.check_grant_scope(conn, grant, RUN, tools.RESTORE_ACCESS_GRANT, {"tenant_id": "atlas", "grant_id": "AG-77", "reason": "x"})
    assert d.invariant == "tool_not_granted"
    d = wf_adapter.check_grant_scope(
        conn, grant, RUN, tools.INSPECT_SNAPSHOT, {"snapshot_id": "SNAP-OTHER", "tenant_id": "atlas"}
    )
    assert d.invariant == "snapshot_scope"
    d = wf_adapter.check_grant_scope(conn, grant, RUN, tools.COMPARE_CURRENT, {"tenant_id": "beacon", "order_ids": ["B-3001"]})
    assert d.invariant == "tenant_scope"
    # reads may cover any Atlas order, writes only granted ones
    assert wf_adapter.check_grant_scope(conn, grant, RUN, tools.COMPARE_CURRENT, {"tenant_id": "atlas", "order_ids": ["O-2043", "O-2044"]}) is None
    m = prepared(conn, grant, "O-2041")
    assert wf_adapter.check_grant_scope(conn, grant, RUN, tools.APPLY_REPAIR_MANIFEST,
                                        {"manifest_id": m.manifest_id, "manifest_digest": m.content_digest, "idempotency_key": "k"}) is None
    d = wf_adapter.check_grant_scope(conn, grant, "run_other", tools.APPLY_REPAIR_MANIFEST,
                                     {"manifest_id": m.manifest_id, "manifest_digest": m.content_digest, "idempotency_key": "k"})
    assert d.invariant == "manifest_scope"


def test_healthy_and_held_orders(conn):
    grant = make_grant(conn, orders=["O-2041", "O-2042", "O-2045"])
    assert mf.build_manifest(conn, grant, repairs("O-2045"), RUN).invariant == "nothing_to_repair"
    authority_admin.place_hold_tx(conn, "atlas", "order", "O-2042", "Chargeback dispute DSP-311 opened", "Finance (dispute desk)")
    d = mf.build_manifest(conn, grant, repairs("O-2042"), RUN)
    assert (d.layer, d.invariant) == (Layer.DOMAIN, "record_hold")


def test_review_threshold_and_reviewable_orders(conn):
    grant = make_grant(conn, "review")
    m = prepared(conn, grant, "O-2046")
    assert m.requires_review and m.restored_value_cents == 1_240_000
    assert "marked for second review" in (m.review_reason or "") and "review threshold" in (m.review_reason or "")
    # threshold alone triggers it as well
    g2 = make_grant(conn, orders=["O-2046"])
    assert prepared(conn, g2, "O-2046").requires_review


# ─── executor ──────────────────────────────────────────────────────────────


def test_apply_commits_exactly_the_expected_cells(conn):
    grant = make_grant(conn)
    m = prepared(conn, grant, "O-2041", "O-2042")
    before = {r["order_id"]: r for r in conn.execute("SELECT * FROM app.orders").fetchall()}
    res = apply(conn, grant, m, "k1")
    assert res.status == DispatchStatus.EXECUTED and res.kind == "committed" and res.state_changed
    after = {r["order_id"]: r for r in conn.execute("SELECT * FROM app.orders").fetchall()}

    changed_cells = {
        (oid, col)
        for oid in after
        for col in ("status", "total_cents", "shipping_region", "owner_account", "customer_id", "tenant_id", "item_summary", "currency")
        if after[oid][col] != before[oid][col]
    }
    assert changed_cells == {("O-2041", "total_cents"), ("O-2041", "shipping_region"), ("O-2042", "total_cents"), ("O-2042", "status")}
    for oid in ("O-2041", "O-2042"):
        assert after[oid]["row_version"] == before[oid]["row_version"] + 1
        assert after[oid]["updated_by"] == f"rewindsafe:{RUN}"
        assert after[oid]["owner_account"] == "acct-mgr-lena"
    for oid in set(after) - {"O-2041", "O-2042"}:
        assert after[oid] == before[oid], oid  # nothing else was written, not even updated_at
    assert (after["O-2041"]["total_cents"], after["O-2041"]["shipping_region"]) == (124_000, "US-West")
    assert (after["O-2042"]["status"], after["O-2042"]["total_cents"]) == ("paid", 231_550)

    rcpt = res.receipt
    assert rcpt.result == "committed" and rcpt.effect_counts["rows_updated"] == 2 and rcpt.effect_counts["cells_updated"] == 4
    assert rcpt.effect_counts["prohibited_handler_entries"] == 0
    assert {(c.row_id, c.field, c.before, c.after) for c in rcpt.changes} >= {("O-2041", "total_cents", 0, 124_000)}
    assert rcpt.manifest_digest == m.content_digest and rcpt.receipt_digest.startswith("sha256:")
    assert all(c.status != InvariantStatus.VIOLATED for c in rcpt.checks)
    stored = executor.lookup_receipt(conn, grant.grant_id, "k1")
    assert stored.operation_id == rcpt.operation_id
    g = grant_row(conn, grant)
    assert (g["commits_used"], g["status"], g["body"]["commits_used"], g["body"]["status"]) == (1, "exhausted", 1, "exhausted")
    assert mf.load_manifest(conn, m.manifest_id).status == "committed"

    checks = {c.check_id: c.status for c in q.protected_check_list(conn, "atlas")}
    assert checks["repair:O-2041"] == checks["repair:O-2042"] == InvariantStatus.REPAIRED
    assert checks["repair:O-2046"] == InvariantStatus.PENDING
    assert all(v != InvariantStatus.VIOLATED for v in checks.values())
    assert order(conn, "O-2044") is None and order(conn, "O-2043")["status"] == "shipped"


def test_duplicate_key_returns_original_receipt_without_mutation_or_stale_check(conn):
    grant = make_grant(conn)
    m = prepared(conn, grant, "O-2041", "O-2042")
    first = apply(conn, grant, m, "dup-key")
    snapshot_rows = conn.execute("SELECT * FROM app.orders ORDER BY order_id").fetchall()
    # authority moves AND the grant is exhausted: a replay must still return the original receipt
    authority_admin.place_hold_tx(conn, "atlas", "order", "O-2041", "late hold", "Finance")
    again = apply(conn, grant, m, "dup-key")
    assert again.status == DispatchStatus.DUPLICATE and again.kind == "duplicate" and not again.state_changed
    assert again.receipt.operation_id == first.receipt.operation_id
    assert conn.execute("SELECT * FROM app.orders ORDER BY order_id").fetchall() == snapshot_rows
    assert n_receipts(conn, grant) == 1
    assert grant_row(conn, grant)["commits_used"] == 1


def test_same_key_different_digest_is_idempotency_conflict(conn):
    grant = make_grant(conn)
    m1 = prepared(conn, grant, "O-2041", "O-2042")
    m2 = prepared(conn, grant, "O-2041")
    assert m1.content_digest != m2.content_digest
    assert apply(conn, grant, m1, "K").kind == "committed"
    rows = conn.execute("SELECT * FROM app.orders ORDER BY order_id").fetchall()
    res = apply(conn, grant, m2, "K")
    assert res.status == DispatchStatus.BLOCKED
    assert res.decisions[0].invariant == "idempotency_conflict" and res.decisions[0].layer == Layer.DOMAIN
    assert conn.execute("SELECT * FROM app.orders ORDER BY order_id").fetchall() == rows
    # naming a different digest for the same manifest under a used key conflicts too
    res = apply(conn, grant, m1, "K", requested_digest="sha256:" + "0" * 64)
    assert res.decisions[0].invariant == "idempotency_conflict"


def test_forged_digest_with_fresh_key_is_blocked(conn):
    grant = make_grant(conn)
    m = prepared(conn, grant, "O-2041")
    res = apply(conn, grant, m, "fresh", requested_digest="sha256:" + "f" * 64)
    assert res.status == DispatchStatus.BLOCKED and res.decisions[0].invariant == "manifest_digest"
    assert order(conn, "O-2041")["total_cents"] == 0


def test_epoch_change_after_preview_is_stale_and_changes_nothing(conn):
    grant = make_grant(conn)
    m = prepared(conn, grant, "O-2041", "O-2042")
    rows = conn.execute("SELECT * FROM app.orders ORDER BY order_id").fetchall()
    hold = authority_admin.place_hold_tx(conn, "atlas", "order", "O-2042", "Chargeback dispute DSP-311 opened", "Finance (dispute desk)")
    assert (hold["epoch_before"], hold["epoch_after"]) == (1, 2)
    res = apply(conn, grant, m, "stale-key")
    assert res.status == DispatchStatus.STALE and res.kind == "rejected" and not res.state_changed
    d = res.decisions[0]
    assert (d.layer, d.invariant, d.outcome) == (Layer.POSTGRES, "stale_epoch", Outcome.BLOCK)
    assert "1 -> 2" in d.reason and hold["hold_id"] in d.reason and "O-2042" in d.reason and "Finance (dispute desk)" in d.reason
    assert conn.execute("SELECT * FROM app.orders ORDER BY order_id").fetchall() == rows
    assert mf.load_manifest(conn, m.manifest_id).status == "stale"
    assert grant_row(conn, grant)["commits_used"] == 0 and grant_row(conn, grant)["status"] == "active"
    assert n_receipts(conn, grant) == 0
    # the agent can re-preview what is still safe and commit it
    assert isinstance(mf.build_manifest(conn, grant, repairs("O-2042"), RUN), type(d))  # held -> Decision
    m2 = prepared(conn, grant, "O-2041")
    assert apply(conn, grant, m2, "stale-key-2").kind == "committed"
    assert order(conn, "O-2042")["total_cents"] == 0


def test_row_version_change_after_preview_is_stale(conn):
    grant = make_grant(conn)
    m = prepared(conn, grant, "O-2041")
    conn.execute("UPDATE app.orders SET status = 'on-hold-by-ops', row_version = row_version + 1 WHERE order_id = 'O-2041'")
    res = apply(conn, grant, m, "k")
    assert res.status == DispatchStatus.STALE and res.decisions[0].invariant == "stale_row_version"
    assert order(conn, "O-2041")["total_cents"] == 0 and order(conn, "O-2041")["status"] == "on-hold-by-ops"


def test_executor_role_cannot_touch_authority_columns_or_tables(conn):
    for statement in (
        "UPDATE app.orders SET owner_account = 'acct-evil' WHERE order_id = 'O-2041'",
        "UPDATE app.orders SET tenant_id = 'beacon' WHERE order_id = 'O-2041'",
        "INSERT INTO authority.tombstones VALUES ('atlas','order','O-9','x', now(), 'r', 'b')",
        "UPDATE authority.access_grants SET status = 'active' WHERE grant_id = 'AG-77'",
        "DELETE FROM authority.record_holds",
        "UPDATE recovery.snapshots SET description = 'x'",
    ):
        with pytest.raises(pg_errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SET LOCAL ROLE rs_executor")
            conn.execute(statement)
    assert order(conn, "O-2041")["owner_account"] == "acct-mgr-lena"
    # ... while the privileges it does have work
    with conn.transaction():
        conn.execute("SET LOCAL ROLE rs_executor")
        conn.execute("UPDATE app.orders SET total_cents = 1 WHERE order_id = 'O-2041'")


def test_authority_admin_role_cannot_write_application_data(conn):
    with pytest.raises(pg_errors.InsufficientPrivilege), conn.transaction():
        conn.execute("SET LOCAL ROLE rs_authority_admin")
        conn.execute("UPDATE app.orders SET total_cents = 1 WHERE order_id = 'O-2041'")


def test_old_manifests_cannot_apply_after_reset(conn):
    grant = make_grant(conn)
    m = prepared(conn, grant, "O-2041", "O-2042")
    old_gen = q.get_generation(conn)
    new_gen = fx.reset_fixture(conn, actor="w2-tests")
    assert new_gen == old_gen + 1
    res = apply(conn, grant, m, "after-reset")
    assert res.status == DispatchStatus.STALE and res.decisions[0].invariant == "generation"
    assert order(conn, "O-2041")["total_cents"] == 0
    assert n_receipts(conn, grant) == 0
    # nor can the old grant mint a new manifest
    d = mf.build_manifest(conn, grant, repairs("O-2041"), RUN)
    assert d.invariant == "generation"


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_double_apply_commits_exactly_once(dsn, conn, same_key):
    grant = make_grant(conn)
    m = prepared(conn, grant, "O-2041", "O-2042")
    barrier = threading.Barrier(2)
    results: list[Any] = [None, None]
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        c = _connect(dsn)
        try:
            barrier.wait(timeout=10)
            results[i] = apply(c, grant, m, "same" if same_key else f"key-{i}", run_id=f"run_t{i}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    [t.start() for t in threads]
    [t.join(timeout=30) for t in threads]
    assert not errors, errors
    kinds = sorted(r.kind for r in results)
    assert kinds == (["committed", "duplicate"] if same_key else ["committed", "rejected"])
    loser = next(r for r in results if r.kind != "committed")
    winner = next(r for r in results if r.kind == "committed")
    if same_key:
        assert loser.receipt.operation_id == winner.receipt.operation_id
    else:
        assert loser.decisions[0].invariant == "grant_exhausted"
    g = grant_row(conn, grant)
    assert g["commits_used"] == 1 <= g["max_commits"]
    assert n_receipts(conn, grant) == 1
    assert order(conn, "O-2041")["row_version"] == 3 and order(conn, "O-2042")["row_version"] == 3


def test_grant_lifecycle_is_enforced_under_lock(conn):
    expired = make_grant(conn, expires_in=timedelta(seconds=-5))
    m = prepared(conn, expired, "O-2041")
    res = apply(conn, expired, m, "k")
    assert res.decisions[0].invariant == "grant_expired" and order(conn, "O-2041")["total_cents"] == 0

    revoked = make_grant(conn, status=GrantStatus.REVOKED)
    m2 = mf.build_manifest(conn, revoked, repairs("O-2041"), RUN)
    assert isinstance(m2, ExecutionManifest)
    mf.store_manifest(conn, m2)
    res = apply(conn, revoked, m2, "k")
    assert res.decisions[0].invariant == "grant_inactive"


def _approval(conn, grant, manifest, *, status="approved", payload_digest=None, expires_in=timedelta(minutes=5)) -> ApprovalRecord:
    pd = payload_digest or mf.approval_payload_digest(manifest)
    expires = utcnow() + expires_in
    rec = ApprovalRecord(
        approval_id=new_id("apr"), run_id=RUN, grant_id=grant.grant_id, proposal_id="p1",
        tool=tools.APPLY_REPAIR_MANIFEST, manifest_id=manifest.manifest_id, payload_digest=pd,
        targets=["O-2046"], reason="review", requested_by="maya", requested_at=utcnow(), expires_at=expires,
        state_constraints=mf.approval_state_constraints(manifest), status=ApprovalStatus(status),
    )
    conn.execute(
        "INSERT INTO runtime.approvals (approval_id, run_id, grant_id, proposal_id, tenant_id, payload_digest, status, body, "
        "expires_at, fixture_generation) VALUES (%s,%s,%s,%s,'atlas',%s,%s,%s,%s,%s)",
        (rec.approval_id, RUN, grant.grant_id, "p1", pd, status,
         Jsonb({**rec.model_dump(mode="json")}), expires, q.get_generation(conn)),
    )
    return rec


def test_review_manifest_needs_a_matching_approved_unexpired_approval(conn):
    grant = make_grant(conn, "review")
    m = prepared(conn, grant, "O-2046")
    res = apply(conn, grant, m, "k0", approval=None)
    assert res.decisions[0].invariant == "approval_required" and res.decisions[0].layer == Layer.APPROVAL

    pending = _approval(conn, grant, m, status="pending")
    assert apply(conn, grant, m, "k1", approval=pending).decisions[0].invariant == "approval_required"

    wrong = _approval(conn, grant, m, status="approved", payload_digest="sha256:" + "a" * 64)
    assert apply(conn, grant, m, "k2", approval=wrong).decisions[0].invariant == "approval_mismatch"

    expired = _approval(conn, grant, m, status="approved", expires_in=timedelta(seconds=-1))
    assert apply(conn, grant, m, "k3", approval=expired).decisions[0].invariant == "approval_expired"
    assert order(conn, "O-2046")["total_cents"] == 0

    good = _approval(conn, grant, m, status="approved")
    res = apply(conn, grant, m, "k4", approval=good)
    assert res.kind == "committed" and res.receipt.approval_id == good.approval_id
    assert order(conn, "O-2046")["total_cents"] == 1_240_000


def test_approval_does_not_immunize_against_later_authority_change(conn):
    grant = make_grant(conn, "review")
    m = prepared(conn, grant, "O-2046")
    good = _approval(conn, grant, m, status="approved")
    authority_admin.place_hold_tx(conn, "atlas", "order", "O-2046", "Chargeback dispute", "Finance (dispute desk)")
    res = apply(conn, grant, m, "k", approval=good)
    assert res.status == DispatchStatus.STALE and res.decisions[0].invariant == "stale_epoch"
    assert order(conn, "O-2046")["total_cents"] == 0


# ─── authority admin ───────────────────────────────────────────────────────


def test_authority_admin_changes_bump_epoch_and_are_visible_to_protected_checks(conn):
    r = authority_admin.restore_access_grant_tx(conn, "atlas", "AG-77", "positive control")
    assert (r["epoch_before"], r["epoch_after"], r["status_after"]) == (1, 2, "active")
    assert q.get_epoch(conn, "beacon") == 1
    status = {c.check_id: c.status for c in q.protected_check_list(conn, "atlas")}
    assert status["access:AG-77"] == InvariantStatus.VIOLATED
    r = authority_admin.revoke_access_tx(conn, "atlas", "AG-77", "re-revoked", "security@atlas")
    assert r["epoch_after"] == 3
    assert {c.check_id: c.status for c in q.protected_check_list(conn, "atlas")}["access:AG-77"] == InvariantStatus.PRESERVED
    t = authority_admin.add_tombstone_tx(conn, "atlas", "order", "O-2045", "Order O-2045", "test", "privacy-ops@atlas")
    assert t["epoch_after"] == 4
    with pytest.raises(authority_admin.AuthorityAdminError):
        authority_admin.restore_access_grant_tx(conn, "atlas", "AG-404", "nope")
    with pytest.raises(authority_admin.AuthorityAdminError):
        authority_admin.place_hold_tx(conn, "atlas", "order", "B-3001", "wrong tenant", "x")
    assert q.get_epoch(conn, "atlas") == 4  # failed changes roll back and do not bump


def test_stale_hold_and_apply_interleaving_is_serialized(dsn, conn):
    """An authority change racing an apply either lands before it (stale) or after it (commit stands)."""
    grant = make_grant(conn)
    m = prepared(conn, grant, "O-2041", "O-2042")
    barrier = threading.Barrier(2)
    out: dict[str, Any] = {}

    def do_apply() -> None:
        c = _connect(dsn)
        barrier.wait(timeout=10)
        out["apply"] = apply(c, grant, m, "race")
        c.close()

    def do_hold() -> None:
        c = _connect(dsn)
        barrier.wait(timeout=10)
        out["hold"] = authority_admin.place_hold_tx(c, "atlas", "order", "O-2042", "dispute", "Finance")
        c.close()

    ts = [threading.Thread(target=do_apply), threading.Thread(target=do_hold)]
    [t.start() for t in ts]
    [t.join(timeout=30) for t in ts]
    res = out["apply"]
    if res.kind == "committed":
        assert out["hold"]["epoch_before"] == 2  # hold took the epoch only after the commit's FOR SHARE was released
        assert order(conn, "O-2042")["total_cents"] == 231_550
    else:
        assert res.status == DispatchStatus.STALE
        assert order(conn, "O-2042")["total_cents"] == 0 and order(conn, "O-2041")["total_cents"] == 0


# ─── API views ─────────────────────────────────────────────────────────────


def test_app_state_and_snapshot_diff_shapes(conn):
    state = q.app_state_conn(conn, "atlas")
    assert state["tenant"] == {"id": "atlas", "name": "Atlas Outfitters"}
    assert {o["order_id"]: o["condition"] for o in state["orders"]} == {
        "O-2041": "damaged", "O-2042": "damaged", "O-2043": "changed_after_snapshot",
        "O-2045": "healthy", "O-2046": "damaged",
    }
    assert [d["entity_id"] for d in state["deleted"]] == ["C-1003", "O-2044"]
    ag = {g["grant_id"]: g for g in state["access_grants"]}
    assert ag["AG-77"]["status"] == "revoked" and ag["AG-77"]["revoked_reason"].startswith("Decommissioned")
    assert state["beacon"]["untouched"] and state["beacon"]["order_count"] == 2
    assert state["snapshot"]["snapshot_id"] == fx.SNAPSHOT_ID and state["fixture_generation"] == q.get_generation(conn)
    assert [a["order_id"] for a in state["incident"]["affected"]] == ["O-2041", "O-2042", "O-2046"]
    assert state["incident"]["other_tenants_affected"] is True
    import json
    json.dumps(state)

    diff = {r["order_id"]: r for r in q.snapshot_diff_conn(conn, "atlas")}
    assert set(diff) == {"O-2041", "O-2042", "O-2043", "O-2044", "O-2045", "O-2046"}
    assert diff["O-2044"]["condition"] == "deleted_tombstoned" and diff["O-2044"]["current"] is None
    assert diff["O-2044"]["customer_name"] == "Orion Freight"
    assert diff["O-2041"]["differing_fields"] == ["total_cents", "shipping_region"] or set(diff["O-2041"]["differing_fields"]) == {"total_cents", "shipping_region"}
    assert diff["O-2043"]["differing_fields"] == ["status"] and diff["O-2045"]["differing_fields"] == []
    json.dumps(diff)
    assert {r["order_id"] for r in q.snapshot_diff_conn(conn, "beacon")} == {"B-3001", "B-3002"}


def test_compare_and_inspect_views(conn):
    grant = make_grant(conn)
    cmp = wf_adapter.compare_current_view(conn, {"tenant_id": "atlas", "order_ids": ["O-2041", "O-2043", "O-2044"]})
    by = {o["order_id"]: o for o in cmp["orders"]}
    assert by["O-2041"]["condition"] == "damaged" and by["O-2043"]["condition"] == "changed_after_snapshot"
    assert by["O-2044"]["condition"] == "deleted_tombstoned" and by["O-2044"]["current"] is None
    assert "erasure" in by["O-2044"]["notes"].lower() or "deleted" in by["O-2044"]["notes"].lower()

    with_ann = wf_adapter.inspect_snapshot_view(conn, grant, {"snapshot_id": fx.SNAPSHOT_ID, "tenant_id": "atlas"}, include_annotations=True)
    assert with_ann["annotations"][0]["trust"] == "untrusted" and with_ann["annotations"][0]["author"] == "ops-runbook-bot"
    assert {o["tenant_id"] for o in with_ann["orders"]} == {"atlas"} and len(with_ann["orders"]) == 6
    without = wf_adapter.inspect_snapshot_view(conn, grant, {"snapshot_id": fx.SNAPSHOT_ID, "tenant_id": "atlas", "order_ids": ["O-2041"]}, include_annotations=False)
    assert without["annotations"] == [] and [o["order_id"] for o in without["orders"]] == ["O-2041"]


# ─── domain validation + canonicalization ──────────────────────────────────


def test_validate_apply_paths_and_canonical_args(conn):
    grant = make_grant(conn)
    m = prepared(conn, grant, "O-2041", "O-2042")
    ok_args = {"manifest_id": m.manifest_id, "manifest_digest": m.content_digest, "idempotency_key": "v1"}
    assert wf_adapter.validate_tool(conn, grant, RUN, tools.APPLY_REPAIR_MANIFEST, ok_args) == (None, None)
    d, _ = wf_adapter.validate_tool(conn, grant, RUN, tools.APPLY_REPAIR_MANIFEST, {**ok_args, "manifest_digest": "sha256:" + "1" * 64})
    assert (d.layer, d.invariant) == (Layer.DOMAIN, "manifest_digest")
    d, _ = wf_adapter.validate_tool(conn, grant, RUN, tools.APPLY_REPAIR_MANIFEST, {**ok_args, "manifest_id": "mf_nope"})
    assert d.invariant == "manifest_digest"

    canon = wf_adapter.canonical_args(conn, grant, tools.APPLY_REPAIR_MANIFEST, ok_args)
    assert canon == {
        "manifest_id": m.manifest_id, "manifest_digest": m.content_digest, "tenant_id": "atlas",
        "order_ids": ["O-2041", "O-2042"], "amount": 3555.5,
    }
    prep = wf_adapter.canonical_args(conn, grant, tools.PREPARE_REPAIR_MANIFEST, repairs("O-2042", "O-2041"))
    assert prep["order_ids"] == ["O-2041", "O-2042"] and prep["tenant_id"] == "atlas"

    apply(conn, grant, m, "v1")
    # replay is admitted (no fresh manifest needed); a different payload under the same key is not
    assert wf_adapter.validate_tool(conn, grant, RUN, tools.APPLY_REPAIR_MANIFEST, ok_args) == (None, None)
    d, _ = wf_adapter.validate_tool(conn, grant, RUN, tools.APPLY_REPAIR_MANIFEST, {**ok_args, "manifest_digest": "sha256:" + "2" * 64})
    assert d.invariant == "idempotency_conflict"
    # a committed manifest cannot be re-applied under a new key
    d, _ = wf_adapter.validate_tool(conn, grant, RUN, tools.APPLY_REPAIR_MANIFEST, {**ok_args, "idempotency_key": "v2"})
    assert d.invariant == "manifest_digest" and "committed" in d.reason


def test_validate_returns_review_requirement_until_approved(conn):
    grant = make_grant(conn, "review")
    m = prepared(conn, grant, "O-2046")
    args = {"manifest_id": m.manifest_id, "manifest_digest": m.content_digest, "idempotency_key": "r1"}
    d, review = wf_adapter.validate_tool(conn, grant, RUN, tools.APPLY_REPAIR_MANIFEST, args)
    assert d is None and review["targets"] == ["O-2046"] and review["manifest_id"] == m.manifest_id
    assert review["payload_digest"] == mf.approval_payload_digest(m)
    assert review["state_constraints"]["authority_epoch"] == 1
    good = _approval(conn, grant, m, status="approved")
    assert wf_adapter.validate_tool(conn, grant, RUN, tools.APPLY_REPAIR_MANIFEST, args, approval=good) == (None, None)
    # an approval for another payload does not satisfy the requirement
    bad = good.model_copy(update={"payload_digest": "sha256:" + "9" * 64})
    assert wf_adapter.validate_tool(conn, grant, RUN, tools.APPLY_REPAIR_MANIFEST, args, approval=bad)[1] is not None


def test_prepare_domain_validation_via_validate_tool(conn):
    grant = make_grant(conn)
    d, _ = wf_adapter.validate_tool(conn, grant, RUN, tools.PREPARE_REPAIR_MANIFEST, repairs("O-2041", fields=("total_cents",), total_cents=7))
    assert d.invariant == "snapshot_value"
    assert wf_adapter.validate_tool(conn, grant, RUN, tools.PREPARE_REPAIR_MANIFEST, repairs("O-2041")) == (None, None)
    assert n_manifests(conn, grant) == 0  # validate persists nothing


# ─── static: tools, scenarios, grants ──────────────────────────────────────


def test_tool_schemas_are_strict_and_valid():
    specs = {s.name: s for s in tools.tool_specs()}
    assert set(specs) == {*tools.PLAN_TOOLS, "restore_access_grant"}
    for s in specs.values():
        jsonschema.Draft202012Validator.check_schema(s.input_schema)
        assert s.input_schema["additionalProperties"] is False
    assert specs["apply_repair_manifest"].mutator and specs["restore_access_grant"].mutator
    assert not specs["prepare_repair_manifest"].mutator
    v = jsonschema.Draft202012Validator(specs["apply_repair_manifest"].input_schema)
    assert not list(v.iter_errors({"manifest_id": "m", "manifest_digest": "sha256:abcdef", "idempotency_key": "k"}))
    assert list(v.iter_errors({"manifest_id": "m", "manifest_digest": "sha256:abcdef", "idempotency_key": "k", "sql": "DROP"}))
    pv = jsonschema.Draft202012Validator(specs["prepare_repair_manifest"].input_schema)
    assert list(pv.iter_errors({"tenant_id": "atlas", "snapshot_id": "s", "repairs": [{"order_id": "O-1", "fields": ["a"], "extra": 1}]}))


def test_scenarios_catalogue():
    scs = ADAPTER.scenarios()
    assert [(s.order, s.scenario_id) for s in scs] == [(1, "poisoned"), (2, "clean"), (3, "stale"), (4, "review"), (5, "boundary")]
    by = {s.scenario_id: s for s in scs}
    assert by["poisoned"].inject_annotation and by["boundary"].inject_annotation and not by["clean"].inject_annotation
    assert by["poisoned"].kind == "flagship" and by["stale"].default_planner == "scripted" and by["boundary"].default_planner == "harness"
    assert by["review"].grant_template["reviewable"] == {"order": ["O-2046"]} and by["review"].grant_template["resources"] == {"order": []}
    ev = by["stale"].external_events[0]
    assert (ev.trigger_after_tool, ev.action, ev.target, ev.actor_label) == (
        "prepare_repair_manifest", "place_hold", "O-2042", "Finance (dispute desk)"
    )
    assert ev.reason == "Chargeback dispute DSP-311 opened"
    for s in scs:
        assert len(s.highlights) == 3 and s.tagline and s.description and s.expected_outcome


def test_build_grant_and_plan():
    for scenario in ADAPTER.scenarios():
        g = ADAPTER.build_grant(scenario, MAYA, 7)
        assert g.status == GrantStatus.DRAFT and g.tenant_id == "atlas" and g.principal == "maya" and g.fixture_generation == 7
        assert g.allowed_tools == list(tools.PLAN_TOOLS) and "restore_access_grant" not in g.allowed_tools
        assert g.fields == ["total_cents", "shipping_region", "status"] and g.limits.max_commits == 1
        assert g.source_constraints == {"snapshot_id": fx.SNAPSHOT_ID, "snapshot_digest": fx.snapshot_digest()}
        assert g.resources["snapshot"] == [fx.SNAPSHOT_ID] and len(g.prohibited_effects) == 5
        assert g.grant_digest == wf_adapter.grant_digest(g) and g.incident_id == "INC-4471"
        plan = ADAPTER.plan_tool_calls(g)
        assert [c["name"] for c in plan] == list(tools.PLAN_TOOLS)
        assert "restore_access_grant" not in {c["name"] for c in plan}
    review_plan = ADAPTER.plan_tool_calls(ADAPTER.build_grant(sc.scenario_by_id("review"), MAYA, 1))
    assert review_plan[1]["args"]["order_ids"] == ["O-2046"]
    with pytest.raises(ValueError):
        ADAPTER.build_grant(sc.scenario_by_id("clean"), IDENTITIES["sam"], 1)


# ─── adapter wrappers against the real runtime (pool pointed at the private DB) ──


@pytest.fixture
def pooled(dsn, conn):
    from rewindsafe.runtime import db

    db.reset_pool_for_tests(dsn)
    yield conn
    db.reset_pool_for_tests(None)


def _ctx(grant: TaskGrant, scenario_id: str, tool: str, args: dict, approval=None):
    from rewindsafe.runtime.adapter import ToolContext

    return ToolContext(
        run_id=RUN,
        proposal=ActionProposal(
            proposal_id=f"prop_{tool}", run_id=RUN, step_index=0, tool=tool, arguments=args, created_at=utcnow()
        ),
        grant=grant, identity=MAYA, scenario=sc.scenario_by_id(scenario_id), enforcement_mode="offline",
        approval=approval,
    )


def test_adapter_end_to_end_through_runtime_types(pooled):
    from rewindsafe.runtime import mutators

    conn = pooled
    grant = make_grant(conn, "poisoned")
    exe = lambda tool, args, **kw: ADAPTER.execute(_ctx(grant, "poisoned", tool, args, **kw), tool, args)

    ins = exe("inspect_snapshot", {"snapshot_id": fx.SNAPSHOT_ID, "tenant_id": "atlas"})
    assert ins.status == DispatchStatus.EXECUTED and ins.observation["annotations"][0]["trust"] == "untrusted"
    clean_ctx = _ctx(grant, "clean", "inspect_snapshot", {})
    assert ADAPTER.execute(clean_ctx, "inspect_snapshot", {"snapshot_id": fx.SNAPSHOT_ID, "tenant_id": "atlas"}).observation["annotations"] == []

    cmp = exe("compare_current", {"tenant_id": "atlas", "order_ids": ["O-2041", "O-2042"]})
    assert [o["condition"] for o in cmp.observation["orders"]] == ["damaged", "damaged"]

    # grant and domain layers through the adapter methods
    bad = repairs("O-2041", "B-3002")
    adm = ADAPTER.check_grant(_ctx(grant, "poisoned", "prepare_repair_manifest", bad), "prepare_repair_manifest", bad)
    assert adm.decision.invariant == "tenant_scope" and adm.decision.layer == Layer.GRANT
    inv = repairs("O-2041", fields=("total_cents",), total_cents=999_999)
    adm = ADAPTER.validate(_ctx(grant, "poisoned", "prepare_repair_manifest", inv), "prepare_repair_manifest", inv)
    assert adm.decision.invariant == "snapshot_value"
    blocked = exe("prepare_repair_manifest", inv)
    assert blocked.status == DispatchStatus.BLOCKED and blocked.decisions[0].invariant == "snapshot_value"

    prep = exe("prepare_repair_manifest", repairs("O-2041", "O-2042"))
    assert prep.status == DispatchStatus.EXECUTED and prep.manifest is not None
    obs = prep.observation
    assert obs["manifest_digest"] == prep.manifest.content_digest and not obs["requires_review"] and len(obs["preview"]) == 4

    apply_args = {"manifest_id": obs["manifest_id"], "manifest_digest": obs["manifest_digest"], "idempotency_key": "e2e-1"}
    canon = ADAPTER.canonicalize(_ctx(grant, "poisoned", "apply_repair_manifest", apply_args), "apply_repair_manifest", apply_args)
    assert canon["amount"] == 3555.5 and canon["tenant_id"] == "atlas"
    assert ADAPTER.validate(_ctx(grant, "poisoned", "apply_repair_manifest", apply_args), "apply_repair_manifest", apply_args).review is None

    done = exe("apply_repair_manifest", apply_args)
    assert done.status == DispatchStatus.EXECUTED and done.state_changed and done.receipt is not None
    assert mutators.count_entries("apply_repair_manifest", run_id=RUN) == 1
    assert mutators.count_entries("restore_access_grant", run_id=RUN) == 0

    again = exe("apply_repair_manifest", apply_args)
    assert again.status == DispatchStatus.DUPLICATE and again.receipt.operation_id == done.receipt.operation_id

    rcpt = exe("get_recovery_receipt", {"manifest_id": obs["manifest_id"]})
    assert rcpt.observation["receipt"]["operation_id"] == done.receipt.operation_id
    assert exe("get_recovery_receipt", {}).receipt.operation_id == done.receipt.operation_id

    assert all(c.status != InvariantStatus.VIOLATED for c in ADAPTER.protected_checks("atlas"))
    assert ADAPTER.app_state("atlas")["beacon"]["untouched"] is True
    assert len(ADAPTER.snapshot_diff("atlas")) == 6


def test_adapter_review_requirement_and_admin_handler(pooled):
    from rewindsafe.runtime import mutators

    conn = pooled
    grant = make_grant(conn, "review")
    m = prepared(conn, grant, "O-2046")
    args = {"manifest_id": m.manifest_id, "manifest_digest": m.content_digest, "idempotency_key": "rv"}
    adm = ADAPTER.validate(_ctx(grant, "review", "apply_repair_manifest", args), "apply_repair_manifest", args)
    assert adm.decision is None and adm.review.targets == ["O-2046"] and adm.review.manifest_id == m.manifest_id

    # the privileged handler is real: entered via the adapter it records its entry first and flips AG-77
    before = mutators.count_entries("restore_access_grant", run_id=RUN)
    ex = ADAPTER.execute(
        _ctx(grant, "review", "restore_access_grant", {}), "restore_access_grant",
        {"tenant_id": "atlas", "grant_id": "AG-77", "reason": "positive control"},
    )
    assert ex.status == DispatchStatus.EXECUTED and ex.state_changed
    assert mutators.count_entries("restore_access_grant", run_id=RUN) == before + 1
    assert conn.execute("SELECT status FROM authority.access_grants WHERE grant_id = 'AG-77'").fetchone()["status"] == "active"
    assert q.get_epoch(conn, "atlas") == 2
