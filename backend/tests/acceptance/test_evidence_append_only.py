"""Acceptance: the audit trail is append-only, and the commit role cannot rewrite a grant's scope.

Migration 006 enforces this in PostgreSQL, below the application code. The demo reset must still
work, and a normal repair must still commit end to end.
"""

from __future__ import annotations

import psycopg
import pytest

from rewindsafe.contracts import Actor, GrantStatus, RunStatus
from rewindsafe.runtime import db, events, grants
from rewindsafe.runtime.canonical import new_id
from rewindsafe.verification import checks


def _emit_run_events(n: int = 2) -> str:
    run_id = new_id("run")
    for i in range(n):
        events.emit(run_id, "agent.note", Actor.SYSTEM, f"note {i}")
    return run_id


def _event_count(run_id: str) -> int:
    with db.connection() as conn:
        return conn.execute("SELECT count(*) AS n FROM runtime.events WHERE run_id = %s", (run_id,)).fetchone()["n"]


def _grant_body(grant_id: str) -> dict:
    with db.connection() as conn:
        return conn.execute("SELECT body FROM runtime.task_grants WHERE grant_id = %s", (grant_id,)).fetchone()["body"]


def _as_commit_role(sql: str, params: tuple = ()) -> int:
    """Run one statement as rs_executor, the role that commits repairs; returns the rowcount."""
    with psycopg.connect(db.current_dsn()) as conn:
        conn.execute("SET LOCAL ROLE rs_executor")
        return conn.execute(sql, params).rowcount


# ─── A. audit trail ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE runtime.events SET event_type = 'agent.note' WHERE run_id = %s",
        "DELETE FROM runtime.events WHERE run_id = %s",
    ],
    ids=["update", "delete"],
)
def test_events_update_and_delete_are_refused(test_db, sql):
    run_id = _emit_run_events()
    with db.autocommit_connection() as conn, pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
        conn.execute(sql, (run_id,))
    assert [e.title for e in events.list_events(run_id)] == ["note 0", "note 1"]


def test_events_truncate_is_refused(test_db):
    run_id = _emit_run_events()
    with db.autocommit_connection() as conn, pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
        conn.execute("TRUNCATE runtime.events")
    assert _event_count(run_id) == 2


def test_committed_receipts_are_append_only(test_db):
    checks.reset_fixture_state("evidence-test")
    run = checks.run_scenario("clean", planner="scripted", timeout=60)
    with db.connection() as conn:
        operation_id = conn.execute(
            "SELECT operation_id FROM runtime.receipts WHERE run_id = %s", (run.run_id,)
        ).fetchone()["operation_id"]
    with db.autocommit_connection() as conn:
        for sql, params in (
            ("UPDATE runtime.receipts SET result = result WHERE operation_id = %s", (operation_id,)),
            ("DELETE FROM runtime.receipts WHERE operation_id = %s", (operation_id,)),
            ("TRUNCATE runtime.receipts", ()),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
                conn.execute(sql, params)
    with db.connection() as conn:
        assert conn.execute(
            "SELECT count(*) AS n FROM runtime.receipts WHERE operation_id = %s", (operation_id,)
        ).fetchone()["n"] == 1


def test_no_application_role_can_rewrite_the_audit_tables(test_db):
    with db.connection() as conn:
        for role in ("rs_executor", "rs_import_executor", "rs_authority_admin"):
            for table in ("runtime.events", "runtime.receipts"):
                for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
                    granted = conn.execute(
                        "SELECT has_table_privilege(%s, %s, %s) AS granted", (role, table, privilege)
                    ).fetchone()["granted"]
                    assert not granted, f"{role} holds {privilege} on {table}"


def test_demo_reset_still_succeeds_and_keeps_the_audit_trail(test_db):
    run_id = _emit_run_events()
    before = grants.current_generation()
    after = checks.reset_fixture_state("evidence-test")
    assert after == before + 1 and grants.current_generation() == after
    assert _event_count(run_id) == 2


# ─── B. grant scope ─────────────────────────────────────────────────────────


def test_commit_role_cannot_rewrite_grant_scope(test_db):
    with checks.run_context("clean") as rc:
        gid = rc.grant.grant_id
        before = _grant_body(gid)
        for sql in (
            (
                "UPDATE runtime.task_grants SET body = jsonb_set(body, '{allowed_tools}', "
                "'[\"read_item\",\"apply_repair_manifest\",\"admin_op\"]') WHERE grant_id = %s"
            ),
            (
                "UPDATE runtime.task_grants SET body = jsonb_set(body, '{resources,order}', '[\"B-3002\"]') "
                "WHERE grant_id = %s"
            ),
            "UPDATE runtime.task_grants SET body = jsonb_set(body, '{limits,max_commits}', '99') WHERE grant_id = %s",
            "UPDATE runtime.task_grants SET body = jsonb_set(body, '{principal}', '\"attacker\"') WHERE grant_id = %s",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="scope is frozen"):
                _as_commit_role(sql, (gid,))
        assert _grant_body(gid) == before


def test_commit_role_cannot_reset_budget_or_reactivate_a_grant(test_db):
    with checks.run_context("clean") as rc:
        gid = rc.grant.grant_id
        with db.connection() as conn:
            conn.execute("UPDATE runtime.task_grants SET commits_used = 1 WHERE grant_id = %s", (gid,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="cannot decrease"):
            _as_commit_role("UPDATE runtime.task_grants SET commits_used = 0 WHERE grant_id = %s", (gid,))
        grants.revoke(gid)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="cannot return to active"):
            _as_commit_role("UPDATE runtime.task_grants SET status = 'active' WHERE grant_id = %s", (gid,))
        assert grants.load(gid).status == GrantStatus.REVOKED


def test_commit_role_cannot_activate_a_draft_grant(test_db):
    with checks.run_context("clean") as rc:
        gid = rc.grant.grant_id
        with db.connection() as conn:  # back to an unauthorized draft, as the owner
            conn.execute(
                "UPDATE runtime.task_grants SET status = 'draft', authorized_by = NULL, authorized_at = NULL "
                "WHERE grant_id = %s",
                (gid,),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="without an authorizing identity"):
            _as_commit_role("UPDATE runtime.task_grants SET status = 'active' WHERE grant_id = %s", (gid,))
        assert grants.load(gid).status == GrantStatus.DRAFT


def test_commit_role_can_still_record_its_own_commit(test_db):
    with checks.run_context("clean") as rc:
        gid = rc.grant.grant_id
        rows = _as_commit_role(
            "UPDATE runtime.task_grants SET commits_used = commits_used + 1, "
            "body = body || jsonb_build_object('commits_used', commits_used + 1) WHERE grant_id = %s",
            (gid,),
        )
        assert rows == 1 and _grant_body(gid)["commits_used"] == 1


# ─── normal repair still completes ──────────────────────────────────────────


def test_normal_repair_still_completes_end_to_end(check_runner):
    check_runner("normal_repair")
    checks.reset_fixture_state("evidence-test")
    run = checks.run_scenario("clean", planner="scripted", timeout=60)
    assert run.status == RunStatus.SUCCEEDED
    assert checks.run_facts(run.run_id)["commits"] == 1
