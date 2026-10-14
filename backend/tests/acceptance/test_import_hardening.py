"""Import recovery hardening: empty manifests, restore-value re-derivation, and authority row locks."""
from __future__ import annotations

import json
import threading
import time

from rewindsafe.contracts import DispatchStatus


def _sample():
    from rewindsafe.api.routes_imports import SampleImportBody, import_sample
    from rewindsafe.runtime.identities import get_identity
    from rewindsafe.workflows.import_recovery import register

    register()
    identity = get_identity("maya")
    return import_sample("warehouse_bins", SampleImportBody(), identity), identity


def _healthy_upload(identity):
    """Current and approved snapshot agree for every record, so nothing is damaged."""
    from rewindsafe.api.routes_imports import ImportBody, import_and_preview
    from rewindsafe.runtime.canonical import digest
    from rewindsafe.workflows.import_recovery import register

    register()
    rows = [{"key": "OWN-1", "tenant": identity.tenant_id, "seats": 11},
            {"key": "OWN-2", "tenant": identity.tenant_id, "seats": 22}]
    authority = [{"key": r["key"], "tenant": identity.tenant_id, "tombstoned": False, "revoked": False,
                  "held": False, "later_edit": False} for r in rows]
    body = ImportBody(
        display_name="Healthy upload", current_format="json", current_data=json.dumps(rows),
        snapshot_format="json", snapshot_data=json.dumps(rows), authority_format="json", authority_data=json.dumps(authority),
        primary_key="key", tenant_column="tenant", repairable_columns=["seat_count"], repairable_types={"seat_count": "integer"},
        authority_columns=["tombstoned", "revoked", "held", "later_edit"],
        column_mapping={"record_id": "key", "tenant_id": "tenant", "seat_count": "seats"},
        approved_snapshot_digest=digest(rows), snapshot_id="healthy-upload-v1",
    )
    return import_and_preview(body, identity)


def _grant(imported, identity, record_ids, fields):
    from rewindsafe.api.routes_imports import GrantBody, create_import_grant
    from rewindsafe.runtime import grants

    draft = create_import_grant(GrantBody(dataset_id=imported["dataset_id"], record_ids=record_ids, repairable_columns=fields), identity)
    return grants.authorize(draft["grant_id"], identity)


def _inventory(dataset_id, record_id):
    from rewindsafe.runtime import db

    with db.connection() as conn:
        return conn.execute(
            "SELECT repair_values,row_version FROM app.import_inventory_items WHERE dataset_id=%s AND record_id=%s",
            (dataset_id, record_id),
        ).fetchone()


def _ledger(grant_id):
    """Commit budget use plus every receipt and manifest the grant produced.

    The grant status is not checked: grants.close() marks any finished run's grant exhausted.
    """
    from rewindsafe.runtime import db

    with db.connection() as conn:
        commits = conn.execute("SELECT commits_used FROM runtime.task_grants WHERE grant_id=%s", (grant_id,)).fetchone()["commits_used"]
        receipts = conn.execute("SELECT count(*) AS n FROM runtime.receipts WHERE grant_id=%s", (grant_id,)).fetchone()["n"]
        manifests = conn.execute("SELECT count(*) AS n FROM runtime.manifests WHERE grant_id=%s", (grant_id,)).fetchone()["n"]
    return {"commits_used": commits, "receipts": receipts, "manifests": manifests}


def _rewrite_manifest(manifest_id, mutate, *, recompute=True):
    """Rewrite a stored manifest body as an owner-level DB writer would.

    The immutability trigger is disabled only inside this transaction, so the test can show what the
    apply-time checks do when that guard is bypassed. With recompute, the digest is refreshed too.
    """
    from psycopg.types.json import Jsonb

    from rewindsafe.contracts import ExecutionManifest
    from rewindsafe.runtime import db
    from rewindsafe.runtime.canonical import digest, to_jsonable

    with db.transaction() as conn:
        conn.execute("ALTER TABLE runtime.manifests DISABLE TRIGGER manifests_immutable")
        body = conn.execute("SELECT body FROM runtime.manifests WHERE manifest_id=%s", (manifest_id,)).fetchone()["body"]
        mutate(body)
        new_digest = None
        if recompute:
            forged = ExecutionManifest.model_validate(body)
            new_digest = digest(forged.model_dump(mode="json", exclude={"status", "created_at", "content_digest"}))
            body = to_jsonable(forged.model_copy(update={"content_digest": new_digest}))
            conn.execute(
                "UPDATE runtime.manifests SET body=%s, content_digest=%s WHERE manifest_id=%s",
                (Jsonb(body), new_digest, manifest_id),
            )
        else:
            conn.execute("UPDATE runtime.manifests SET body=%s WHERE manifest_id=%s", (Jsonb(body), manifest_id))
        conn.execute("ALTER TABLE runtime.manifests ENABLE TRIGGER manifests_immutable")
    return new_digest


def _empty_changes(body):
    body["changes"] = []


def _set_change_value(value):
    def mutate(body):
        for change in body["changes"]:
            if change["row_id"] == "SKU-402" and change["field"] == "quantity":
                change["new_value"] = value
    return mutate


def _tamper_snapshot(snapshot_id, record_id, field, value):
    """Change a snapshot's stored row copy. Its digest covers only source_records, so the digest still matches."""
    from psycopg.types.json import Jsonb

    from rewindsafe.runtime import db

    with db.transaction() as conn:
        conn.execute("SET LOCAL rewindsafe.fixture_reset = 'on'")  # snapshots are immutable outside maintenance mode
        content = conn.execute("SELECT content FROM recovery.import_snapshots WHERE snapshot_id=%s", (snapshot_id,)).fetchone()["content"]
        for row in content["rows"]:
            if row["record_id"] == record_id:
                row["repair_values"][field] = value
        conn.execute("UPDATE recovery.import_snapshots SET content=%s WHERE snapshot_id=%s", (Jsonb(content), snapshot_id))


def _pause_after_prepare(monkeypatch):
    """Hold the scripted run right after its manifest is prepared, so the test can change stored state first.

    ``state["digest"]``, when set, replaces the manifest digest the planner passes to apply.
    """
    from rewindsafe.workflows.import_recovery.adapter import ADAPTER

    state = {"ready": threading.Event(), "proceed": threading.Event(), "manifest_id": None, "digest": None, "apply": []}
    original = ADAPTER.execute

    def hook(ctx, tool, args):
        if tool == "apply_repair_manifest" and state["digest"]:
            args = {**args, "manifest_digest": state["digest"]}
        result = original(ctx, tool, args)
        if tool == "prepare_repair_manifest" and result.status == DispatchStatus.EXECUTED:
            state["manifest_id"] = result.observation["manifest_id"]
            state["ready"].set()
            assert state["proceed"].wait(10), "test did not release the run after editing stored state"
        if tool == "apply_repair_manifest":
            state["apply"].append(result)
        return result

    monkeypatch.setattr(ADAPTER, "execute", hook)
    return state


def _apply_waits_on(needle, timeout=15.0):
    """True once some backend session is blocked on a lock whose statement mentions ``needle``."""
    from rewindsafe.runtime import db

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with db.connection() as conn:
            waiting = conn.execute(
                "SELECT 1 AS hit FROM pg_stat_activity WHERE wait_event_type='Lock' AND query ILIKE %s", (f"%{needle}%",),
            ).fetchone()
        if waiting:
            return True
        time.sleep(0.1)
    return False


def test_in_scope_request_with_nothing_damaged_is_refused_at_prepare(test_db):
    """Calls the adapter directly: the scripted planner stops at compare when nothing needs repair, so
    prepare is only reachable by a planner that asks for it. Nothing may be stored or committed."""
    from types import SimpleNamespace

    from rewindsafe.runtime.adapter import ToolContext
    from rewindsafe.runtime.identities import get_identity
    from rewindsafe.workflows.import_recovery.adapter import ADAPTER

    identity = get_identity("maya")
    imported = _healthy_upload(identity)
    grant = _grant(imported, identity, ["OWN-1", "OWN-2"], ["seat_count"])
    args = {"tenant_id": identity.tenant_id, "snapshot_id": grant.source_constraints["snapshot_id"],
            "repairs": [{"order_id": rid, "fields": ["seat_count"]} for rid in ["OWN-1", "OWN-2"]]}
    ctx = ToolContext(run_id="run_prepare_refusal", proposal=SimpleNamespace(proposal_id="prp_prepare_refusal"),
                      grant=grant, identity=identity, scenario=None, enforcement_mode="offline")
    result = ADAPTER.execute(ctx, "prepare_repair_manifest", args)
    assert result.status == DispatchStatus.BLOCKED
    assert result.observation["invariant"] == "nothing_to_repair"
    assert _ledger(grant.grant_id) == {"commits_used": 0, "receipts": 0, "manifests": 0}


def test_emptied_stored_manifest_is_refused_at_apply_before_the_commit_is_spent(test_db, monkeypatch):
    from rewindsafe.agent import loop
    from rewindsafe.cli import stream_run

    imported, identity = _sample()
    grant = _grant(imported, identity, ["SKU-402"], ["quantity"])
    before = _inventory(imported["dataset_id"], "SKU-402")
    state = _pause_after_prepare(monkeypatch)
    run = loop.start_run(grant.grant_id, identity, planner="scripted")
    assert state["ready"].wait(10), "scripted planner did not prepare its manifest"
    try:
        state["digest"] = _rewrite_manifest(state["manifest_id"], _empty_changes)
    finally:
        state["proceed"].set()
    assert stream_run(run.run_id, decision=None, timeout_s=40)
    assert state["apply"], "apply was never reached"
    assert state["apply"][-1].status == DispatchStatus.BLOCKED
    assert state["apply"][-1].observation["invariant"] == "nothing_to_repair"
    assert _inventory(imported["dataset_id"], "SKU-402") == before
    assert _ledger(grant.grant_id) == {"commits_used": 0, "receipts": 0, "manifests": 1}


def test_tampered_stored_restore_value_is_refused_at_apply_by_manifest_digest(test_db, monkeypatch):
    from rewindsafe.agent import loop
    from rewindsafe.cli import stream_run

    imported, identity = _sample()
    grant = _grant(imported, identity, ["SKU-402"], ["quantity"])
    before = _inventory(imported["dataset_id"], "SKU-402")
    state = _pause_after_prepare(monkeypatch)
    run = loop.start_run(grant.grant_id, identity, planner="scripted")
    assert state["ready"].wait(10), "scripted planner did not prepare its manifest"
    try:
        _rewrite_manifest(state["manifest_id"], _set_change_value(999), recompute=False)
    finally:
        state["proceed"].set()
    assert stream_run(run.run_id, decision=None, timeout_s=40)
    assert state["apply"], "apply was never reached"
    assert state["apply"][-1].status == DispatchStatus.BLOCKED
    assert state["apply"][-1].observation["invariant"] == "manifest_digest"
    assert _inventory(imported["dataset_id"], "SKU-402") == before
    assert _ledger(grant.grant_id) == {"commits_used": 0, "receipts": 0, "manifests": 1}


def test_forged_manifest_is_refused_against_digest_covered_source_records(test_db, monkeypatch):
    """A writer who rewrites the manifest (with a fresh digest) and the snapshot's unsigned row copy still fails:
    restore values must be re-derived from source_records, which the snapshot digest does cover."""
    from rewindsafe.agent import loop
    from rewindsafe.cli import stream_run

    imported, identity = _sample()
    grant = _grant(imported, identity, ["SKU-402"], ["quantity"])
    before = _inventory(imported["dataset_id"], "SKU-402")
    state = _pause_after_prepare(monkeypatch)
    run = loop.start_run(grant.grant_id, identity, planner="scripted")
    assert state["ready"].wait(10), "scripted planner did not prepare its manifest"
    try:
        _tamper_snapshot(imported["snapshot_id"], "SKU-402", "quantity", 999)
        state["digest"] = _rewrite_manifest(state["manifest_id"], _set_change_value(999))
    finally:
        state["proceed"].set()
    assert stream_run(run.run_id, decision=None, timeout_s=40)
    assert state["apply"], "apply was never reached"
    assert state["apply"][-1].status == DispatchStatus.BLOCKED
    assert state["apply"][-1].observation["invariant"] == "snapshot_value"
    assert _inventory(imported["dataset_id"], "SKU-402") == before
    assert _ledger(grant.grant_id) == {"commits_used": 0, "receipts": 0, "manifests": 1}


def test_apply_waits_for_authority_row_lock_and_then_sees_a_hold_placed_during_the_wait(test_db, monkeypatch):
    import psycopg

    from rewindsafe.agent import loop
    from rewindsafe.cli import stream_run
    from rewindsafe.runtime import db

    imported, identity = _sample()
    grant = _grant(imported, identity, ["SKU-402"], ["quantity"])
    before = _inventory(imported["dataset_id"], "SKU-402")
    state = _pause_after_prepare(monkeypatch)
    run = loop.start_run(grant.grant_id, identity, planner="scripted")
    assert state["ready"].wait(10), "scripted planner did not prepare its manifest"
    writer = psycopg.connect(db.current_dsn())
    try:
        # A concurrent authority change: hold SKU-402 but do not commit yet.
        writer.execute(
            "UPDATE recovery.import_authority_state SET held=true WHERE dataset_id=%s AND record_id='SKU-402'",
            (imported["dataset_id"],),
        )
        state["proceed"].set()
        assert _apply_waits_on("import_authority_state"), "apply did not wait on the authority row lock"
    finally:
        writer.commit()
        writer.close()
        state["proceed"].set()
    assert stream_run(run.run_id, decision=None, timeout_s=40)
    assert state["apply"], "apply was never reached"
    assert state["apply"][-1].status == DispatchStatus.STALE
    assert _inventory(imported["dataset_id"], "SKU-402") == before
    assert _ledger(grant.grant_id) == {"commits_used": 0, "receipts": 0, "manifests": 1}
