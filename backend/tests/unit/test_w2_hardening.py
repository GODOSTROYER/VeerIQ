"""W2 hardening tests: migration 002 (executor least privilege + RLS), fixture status, annotations."""

from __future__ import annotations

import psycopg
import pytest
from psycopg import errors as pg_errors

from rewindsafe.workflows.rewindsafe import executor
from rewindsafe.workflows.rewindsafe import fixture as fx
from rewindsafe.workflows.rewindsafe import queries as q

from .test_w2_workflow import apply, conn, dsn, make_grant, order, prepared  # noqa: F401


def _as_executor(conn, tenant: str | None, sql: str):
    conn.autocommit = False
    try:
        if tenant:
            conn.execute("SELECT set_config('rewindsafe.tenant', %s, true)", (tenant,))
        conn.execute("SET LOCAL ROLE rs_executor")
        return conn.execute(sql)
    finally:
        conn.rollback()
        conn.autocommit = True


def test_executor_rls_limits_orders_to_current_tenant(conn):
    cur = _as_executor(conn, "atlas", "UPDATE app.orders SET row_version = row_version WHERE order_id = 'O-2041'")
    assert cur.rowcount == 1
    cur = _as_executor(conn, "atlas", "UPDATE app.orders SET row_version = row_version WHERE order_id = 'B-3002'")
    assert cur.rowcount == 0
    cur = _as_executor(conn, None, "UPDATE app.orders SET row_version = row_version WHERE order_id = 'O-2041'")
    assert cur.rowcount == 0


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE runtime.approvals SET status = 'approved'",
        "UPDATE runtime.task_grants SET expires_at = now()",
        "UPDATE runtime.receipts SET result = 'x'",
        "UPDATE app.orders SET owner_account = 'attacker'",
    ],
)
def test_executor_cannot_touch_authority_columns(conn, sql):
    with pytest.raises(pg_errors.InsufficientPrivilege):
        _as_executor(conn, "atlas", sql)


def test_commit_still_works_with_rls_and_fixture_status_reports_it(conn):
    assert q.fixture_status_conn(conn)["dirty"] is False
    grant = make_grant(conn, "clean")
    m = prepared(conn, grant, "O-2041")
    res = apply(conn, grant, m)
    assert res.kind == "committed"
    st = q.fixture_status_conn(conn)
    assert st["dirty"] is True and "O-2041" in st["repaired_orders"]
    state = q.app_state_conn(conn, "atlas")
    assert state["fixture"]["dirty"] is True
    fx.reset_fixture(conn, actor="t")
    assert q.fixture_status_conn(conn)["dirty"] is False


def test_app_state_exposes_untrusted_annotations(conn):
    anns = q.app_state_conn(conn, "atlas")["snapshot"]["annotations"]
    assert anns and anns[0]["annotation_id"] == fx.ANNOTATION_ID
    assert anns[0]["trust"] == "untrusted" and anns[0]["body"] == fx.ANN9_BODY
