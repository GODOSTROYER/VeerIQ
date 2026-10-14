"""W4 unit tests for the HTTP layer. No database and no other workstream required.

Runtime modules that other workstreams own are replaced by empty stand-ins only
when they cannot be imported yet; every behavior the tests rely on is patched
explicitly, so the same tests keep passing once the real modules exist.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _ensure_module(name: str) -> None:
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        module = ModuleType(name)
        sys.modules[name] = module
        parent, _, child = name.rpartition(".")
        setattr(importlib.import_module(parent), child, module)


for _name in (
    "rewindsafe.runtime.grants",
    "rewindsafe.runtime.approvals",
    "rewindsafe.runtime.receipts",
    "rewindsafe.runtime.armoriq_gateway",
):
    _ensure_module(_name)

from fastapi.testclient import TestClient

from rewindsafe.api import app as app_module
from rewindsafe.api import (
    queries,
    routes_admin,
    routes_runs,
    routes_system,
    sse,
    status,
    verification_jobs,
)
from rewindsafe.api.app import create_app
from rewindsafe.contracts import (
    Actor,
    ApprovalRecord,
    GrantStatus,
    Run,
    RunEvent,
    RunStatus,
    ScenarioSpec,
    TaskGrant,
)
from rewindsafe.runtime import approvals, events, grants, receipts

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(run_startup=False))


def login(client: TestClient, identity_id: str) -> TestClient:
    assert client.post("/api/session", json={"identity_id": identity_id}).status_code == 200
    return client


def make_grant(tenant: str = "atlas", status: GrantStatus = GrantStatus.DRAFT, principal: str = "maya") -> TaskGrant:
    return TaskGrant(
        grant_id="grant_1",
        workflow="rewindsafe.order_repair",
        scenario_id="clean",
        principal=principal,
        principal_email="nova.reyes@atlas.example",
        tenant_id=tenant,
        purpose="repair",
        allowed_tools=["inspect_snapshot"],
        resources={"order": ["O-2041"]},
        status=status,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        fixture_generation=1,
        grant_digest="sha256:x",
    )


def make_run(status: RunStatus = RunStatus.PLANNING) -> Run:
    return Run(
        run_id="run_1",
        grant_id="grant_1",
        scenario_id="clean",
        workflow="rewindsafe.order_repair",
        planner="scripted",
        planner_kind="scripted",
        enforcement_mode="offline",
        status=status,
        fixture_generation=1,
        created_by="maya",
        created_at=NOW,
        updated_at=NOW,
    )


def make_event(seq: int, type_: str = "agent.note", run_id: str = "run_1") -> RunEvent:
    return RunEvent(seq=seq, run_id=run_id, ts=NOW, type=type_, actor=Actor.AGENT, title=f"event {seq}")


# ─── sessions ──────────────────────────────────────────────────────────────


def test_identities_are_public(client):
    body = client.get("/api/identities").json()
    assert {i["identity_id"] for i in body} == {"maya", "dev", "sam"}


def test_session_cookie_flags_and_roundtrip(client):
    response = client.post("/api/session", json={"identity_id": "maya"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "rs_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    me = client.get("/api/session").json()
    assert me["identity_id"] == "maya" and me["role"] == "operator" and me["tenant_id"] == "atlas"


def test_caller_supplied_role_and_tenant_are_ignored(client):
    response = client.post(
        "/api/session",
        json={"identity_id": "maya", "role": "reviewer", "tenant_id": "beacon", "email": "evil@x.example"},
    )
    assert response.json()["role"] == "operator"
    assert client.get("/api/session").json()["tenant_id"] == "atlas"


def test_unknown_identity_and_missing_cookie(client):
    assert client.post("/api/session", json={"identity_id": "root"}).status_code == 404
    response = client.get("/api/session")
    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "unauthenticated", "message": "Sign in as a demo identity first."}
    }


def test_tampered_cookie_is_rejected(client):
    client.cookies.set("rs_session", "maya")
    assert client.get("/api/session").status_code == 401
    client.cookies.set("rs_session", "garbage.signature.value")
    assert client.get("/api/session").status_code == 401


def test_cookie_signed_with_other_secret_is_rejected(client, monkeypatch):
    login(client, "maya")
    monkeypatch.setattr("rewindsafe.api.auth.get_settings", lambda: SimpleNamespace(session_secret="another"))
    assert client.get("/api/session").status_code == 401


def test_logout_clears_session(client):
    login(client, "maya")
    assert client.post("/api/session/logout").json() == {"ok": True}
    assert client.get("/api/session").status_code == 401


# ─── error format & routing ────────────────────────────────────────────────


def test_validation_error_uses_error_format(client):
    response = client.post("/api/session", json={})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_request" and "identity_id" in error["message"]


def test_unknown_api_route_is_json_404_for_every_method(client):
    for method in ("get", "post", "delete"):
        response = getattr(client, method)("/api/nope")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_protected_routes_require_session(client):
    for path in ("/api/app/state", "/api/app/protected-checks", "/api/runs", "/api/metrics", "/api/approvals"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/grants/draft", json={"scenario_id": "clean"}).status_code == 401


def test_role_enforcement(client):
    login(client, "dev")  # reviewer
    for path, body in (
        ("/api/grants/draft", {"scenario_id": "clean"}),
        ("/api/grants/g/authorize", None),
        ("/api/runs", {"grant_id": "g"}),
        ("/api/runs/r/cancel", None),
        ("/api/admin/reset", None),
        ("/api/admin/positive-control", None),
        ("/api/verification/run", None),
    ):
        response = client.post(path, json=body) if body is not None else client.post(path)
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "operator_required"


def test_cors_allows_dev_origins_with_credentials(client):
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        response = client.options(
            "/api/session",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"
    blocked = client.options(
        "/api/session",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in blocked.headers


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


# ─── system status ─────────────────────────────────────────────────────────


class FakeSettings(SimpleNamespace):
    def effective_enforcement(self):
        return "live" if self.armoriq_api_key else "offline"


def fake_settings(**overrides):
    base = dict(
        session_secret="x",
        enforcement="auto",
        armoriq_api_key="",
        armoriq_env="production",
        armoriq_session_mode="sdk",
        armoriq_user_email="",
        planner="auto",
        anthropic_api_key="",
        anthropic_model="claude-sonnet-5-5",
        openai_api_key="",
        openai_model="gpt-5.5",
    )
    base.update(overrides)
    return FakeSettings(**base)


@contextmanager
def _ok_connection():
    yield SimpleNamespace(execute=lambda *_a, **_k: SimpleNamespace(fetchone=lambda: {"ok": 1}))


def patch_status(monkeypatch, settings, describe):
    monkeypatch.setattr(status, "get_settings", lambda: settings)
    monkeypatch.setattr(status.db, "connection", _ok_connection)
    monkeypatch.setattr(status.grants, "current_generation", lambda: 7, raising=False)
    gateway = SimpleNamespace(describe=lambda: describe)
    monkeypatch.setattr(status.armoriq_gateway, "get_gateway", lambda: gateway, raising=False)


def test_status_simulated_and_scripted_are_labeled(client, monkeypatch):
    describe = {
        "mode": "offline", "simulated": True, "sdk_version": "0.6.10", "session_mode": "sdk",
        "env": "production", "configured": False, "user_email": "",
    }
    patch_status(monkeypatch, fake_settings(), describe)
    body = client.get("/api/system/status").json()
    assert body["enforcement"] == {
        "mode": "offline", "simulated": True, "sdk_version": "0.6.10", "session_mode": "sdk",
        "env": "production", "configured": False, "user_email_set": False, "readiness": None,
    }
    assert body["planner"]["kind"] == "scripted" and body["planner"]["configured_llm"] is False
    assert body["planner"]["available_providers"] == [] and body["planner"]["provider"] is None
    assert body["database"] == {"ok": True} and body["fixture_generation"] == 7
    msgs = {w["message"]: w["level"] for w in body["warnings"]}
    assert msgs["ArmorIQ enforcement is SIMULATED (no ARMORIQ_API_KEY)"] == "warn"
    assert msgs["Agent uses the scripted planner (no LLM key configured)"] == "info"
    assert body["contract_version"]


def test_status_live_with_llm_has_no_mode_warnings(client, monkeypatch):
    describe = {
        "mode": "live", "simulated": False, "sdk_version": "0.6.10", "session_mode": "sdk",
        "env": "production", "configured": True, "user_email": "me@example.com",
    }
    patch_status(monkeypatch, fake_settings(armoriq_api_key="ak_test_x", anthropic_api_key="sk-x"), describe)
    body = client.get("/api/system/status").json()
    assert body["enforcement"]["mode"] == "live" and body["enforcement"]["user_email_set"] is True
    p = body["planner"]
    assert (p["kind"], p["name"], p["provider"], p["configured_llm"]) == ("llm", "anthropic:claude-sonnet-5-5", "anthropic", True)
    assert p["available_providers"] == ["anthropic"]
    assert not [w for w in body["warnings"] if "SIMULATED" in w["message"] or "scripted" in w["message"]]


def test_planner_auto_order_prefers_groq_over_openai(client, monkeypatch):
    patch_status(monkeypatch, fake_settings(groq_api_key="gsk_x", openai_api_key="sk-x"), {"mode": "offline", "simulated": True})
    p = client.get("/api/system/status").json()["planner"]
    assert p["name"] == "groq:openai/gpt-oss-120b" and p["available_providers"] == ["groq", "openai"]
    assert p["label"] == "Live LLM - Groq gpt-oss-120b"


def test_status_never_exposes_secrets(client, monkeypatch):
    describe = {"mode": "live", "simulated": False, "configured": True, "user_email": "me@example.com"}
    patch_status(monkeypatch, fake_settings(armoriq_api_key="ak_live_SECRET", anthropic_api_key="sk-SECRET"), describe)
    text = client.get("/api/system/status").text
    assert "SECRET" not in text and "me@example.com" not in text


def test_status_reports_database_down(client, monkeypatch):
    patch_status(monkeypatch, fake_settings(), {"mode": "offline", "simulated": True})

    @contextmanager
    def broken():
        raise RuntimeError("connection refused")
        yield

    monkeypatch.setattr(status.db, "connection", broken)
    body = client.get("/api/system/status").json()
    assert body["database"] == {"ok": False} and body["fixture_generation"] is None
    assert {"level": "error", "code": "database_unreachable", "message": "Database is unreachable"} in body["warnings"]


# ─── scenarios, grants, runs ───────────────────────────────────────────────


def make_scenario(sid: str, order: int, default_planner: str = "auto") -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id=sid, workflow="rewindsafe.order_repair", title=sid, tagline="t", description="d",
        kind="baseline", order=order, default_planner=default_planner, grant_template={},
    )


@pytest.fixture()
def scenarios(monkeypatch):
    items = [make_scenario("stale", 3, "scripted"), make_scenario("poisoned", 1), make_scenario("clean", 2)]
    adapter = SimpleNamespace(scenarios=lambda: items, workflow_id="rewindsafe.order_repair")
    adapters = {adapter.workflow_id: adapter}
    monkeypatch.setattr(routes_runs, "get_adapter", lambda workflow: adapters[workflow])
    monkeypatch.setattr(routes_runs, "get_workflow_adapter", lambda: adapter)
    monkeypatch.setattr(routes_system, "get_workflow_adapter", lambda: adapter)
    return items


def test_scenarios_sorted_by_order(client, scenarios):
    assert [s["scenario_id"] for s in client.get("/api/scenarios").json()] == ["poisoned", "clean", "stale"]


def test_draft_grant_unknown_scenario_and_success(client, scenarios, monkeypatch):
    login(client, "maya")
    assert client.post("/api/grants/draft", json={"scenario_id": "nope"}).status_code == 404
    seen = {}

    def create_draft(adapter, scenario, identity):
        seen["scenario"], seen["who"] = scenario.scenario_id, identity.identity_id
        return make_grant()

    monkeypatch.setattr(grants, "create_draft", create_draft, raising=False)
    response = client.post("/api/grants/draft", json={"scenario_id": "clean", "principal": "dev"})
    assert response.status_code == 200 and response.json()["status"] == "draft"
    assert seen == {"scenario": "clean", "who": "maya"}  # the session decides the principal


def test_draft_for_other_tenant_is_refused(client, scenarios, monkeypatch):
    login(client, "sam")
    monkeypatch.setattr(grants, "create_draft", lambda *_: make_grant(tenant="atlas"), raising=False)
    response = client.post("/api/grants/draft", json={"scenario_id": "clean"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "tenant_mismatch"


def test_grant_reads_are_tenant_scoped(client, monkeypatch):
    monkeypatch.setattr(grants, "load", lambda gid: make_grant(), raising=False)
    login(client, "sam")
    assert client.get("/api/grants/grant_1").status_code == 404
    assert client.post("/api/grants/grant_1/authorize").status_code == 404
    login(client, "dev")
    assert client.get("/api/grants/grant_1").json()["grant_id"] == "grant_1"


def test_authorize_requires_principal_and_draft(client, monkeypatch):
    state = {"grant": make_grant(principal="maya")}
    monkeypatch.setattr(grants, "load", lambda gid: state["grant"], raising=False)
    monkeypatch.setattr(
        grants, "authorize", lambda gid, who: state["grant"].model_copy(update={"status": GrantStatus.ACTIVE}),
        raising=False,
    )
    login(client, "maya")
    assert client.post("/api/grants/grant_1/authorize").json()["status"] == "active"
    state["grant"] = make_grant(status=GrantStatus.ACTIVE)
    response = client.post("/api/grants/grant_1/authorize")
    assert response.status_code == 409 and response.json()["error"]["code"] == "grant_not_draft"
    state["grant"] = make_grant(principal="someone-else")
    response = client.post("/api/grants/grant_1/authorize")
    assert response.status_code == 403 and response.json()["error"]["code"] == "not_grant_principal"


def test_resolve_planner():
    assert routes_runs.resolve_planner(None, "scripted") == "scripted"
    assert routes_runs.resolve_planner("auto", "harness") == "harness"
    assert routes_runs.resolve_planner("llm", "scripted") == "llm"
    assert routes_runs.resolve_planner("scripted", "auto") == "scripted"


def test_start_run_needs_active_grant_and_passes_planner(client, scenarios, monkeypatch):
    state = {"grant": make_grant(status=GrantStatus.DRAFT)}
    monkeypatch.setattr(grants, "load", lambda gid: state["grant"], raising=False)
    calls = []

    def fake_start_run(grant_id, identity, *, planner="auto"):
        calls.append((grant_id, identity.identity_id, planner))
        return make_run()

    monkeypatch.setattr(routes_runs, "agent_api", lambda: SimpleNamespace(start_run=fake_start_run))
    login(client, "maya")
    response = client.post("/api/runs", json={"grant_id": "grant_1"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "grant_not_active"
    state["grant"] = make_grant(status=GrantStatus.ACTIVE).model_copy(update={"scenario_id": "stale"})
    assert client.post("/api/runs", json={"grant_id": "grant_1"}).status_code == 200
    assert client.post("/api/runs", json={"grant_id": "grant_1", "planner": "llm"}).status_code == 200
    assert calls == [("grant_1", "maya", "scripted"), ("grant_1", "maya", "llm")]
    assert client.post("/api/runs", json={"grant_id": "grant_1", "planner": "gpt"}).status_code == 400


def test_start_run_translates_agent_errors(client, scenarios, monkeypatch):
    monkeypatch.setattr(grants, "load", lambda gid: make_grant(status=GrantStatus.ACTIVE), raising=False)

    def boom(*_a, **_k):
        raise ValueError("grant expired")

    monkeypatch.setattr(routes_runs, "agent_api", lambda: SimpleNamespace(start_run=boom))
    login(client, "maya")
    response = client.post("/api/runs", json={"grant_id": "grant_1"})
    assert response.status_code == 409 and response.json()["error"]["message"] == "grant expired"


def test_unhandled_exception_is_generic_500(monkeypatch):
    local = TestClient(create_app(run_startup=False), raise_server_exceptions=False)
    monkeypatch.setattr(queries, "list_runs_for_tenant", lambda *_: (_ for _ in ()).throw(RuntimeError("pw=hunter2")))
    login(local, "maya")
    response = local.get("/api/runs")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error" and "hunter2" not in response.text


def test_run_reads_are_tenant_scoped(client, monkeypatch):
    monkeypatch.setattr(queries, "get_run_with_tenant", lambda rid: (make_run(), "atlas"))
    monkeypatch.setattr(events, "list_events", lambda rid, after=0, limit=500: [make_event(1), make_event(2)])
    monkeypatch.setattr(routes_runs.events, "list_events", events.list_events)
    login(client, "sam")
    for path in (
        "/api/runs/run_1",
        "/api/runs/run_1/events/list",
        "/api/runs/run_1/evidence",
        "/api/runs/run_1/sealed-evidence",
    ):
        assert client.get(path).status_code == 404, path
    assert client.post("/api/runs/run_1/cancel").status_code == 404
    login(client, "dev")
    listed = client.get("/api/runs/run_1/events/list").json()
    assert [e["seq"] for e in listed] == [1, 2]
    login(client, "maya")
    monkeypatch.setattr(receipts, "build_evidence", lambda rid: {"run": rid, "created": NOW}, raising=False)
    evidence = client.get("/api/runs/run_1/evidence")
    assert evidence.status_code == 200
    assert evidence.headers["content-disposition"].startswith("attachment;")
    assert evidence.json()["run"] == "run_1"
    monkeypatch.setattr(
        routes_runs.sealed_evidence,
        "build_sealed_evidence",
        lambda rid: {"schema": "test", "run": rid},
    )
    sealed = client.get("/api/runs/run_1/sealed-evidence")
    assert sealed.status_code == 200
    assert sealed.headers["content-disposition"].startswith("attachment;")
    assert sealed.json()["run"] == "run_1"


def test_signing_public_key_requires_auth_and_matches_signed_export(client, tmp_path, monkeypatch):
    from rewindsafe.runtime import sealed_evidence

    key_path = tmp_path / ".data" / "signing.pem"
    monkeypatch.setattr(sealed_evidence, "KEY_PATH", key_path)
    signer = sealed_evidence._private_key(key_path)
    envelope = sealed_evidence.seal_payload(
        {
            "run": {"run_id": "key-route-test"},
            "events": [{"seq": 1, "type": "run.finished", "run_id": "key-route-test"}],
        },
        signer,
    )

    assert client.get("/api/evidence/signing-public-key").status_code == 401
    login(client, "maya")
    first = client.get("/api/evidence/signing-public-key")
    second = client.get("/api/evidence/signing-public-key")
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("application/x-pem-file")
    assert first.headers["content-disposition"] == 'attachment; filename="workspace-public-key.pem"'
    assert first.headers["cache-control"] == "no-store"
    assert first.content == second.content
    assert b"PRIVATE KEY" not in first.content
    assert sealed_evidence.verify_sealed_evidence(
        envelope, sealed_evidence.load_public_key(first.content)
    )["signer_identity_trusted"] is True
    if os.name != "nt":  # NTFS has no POSIX mode bits; Windows reports 0o666 for any writable file
        assert key_path.stat().st_mode & 0o777 == 0o600


def test_cancel_run_goes_through_agent(client, monkeypatch):
    monkeypatch.setattr(queries, "get_run_with_tenant", lambda rid: (make_run(), "atlas"))
    monkeypatch.setattr(
        routes_runs, "agent_api",
        lambda: SimpleNamespace(cancel_run=lambda rid, who: make_run(RunStatus.CANCELLED)),
    )
    login(client, "maya")
    assert client.post("/api/runs/run_1/cancel").json()["status"] == "cancelled"


def test_run_listing_is_filtered_in_sql_by_session_tenant(client, monkeypatch):
    seen = []
    monkeypatch.setattr(queries, "list_runs_for_tenant", lambda tenant, limit=30: seen.append(tenant) or [make_run()])
    login(client, "sam")
    assert len(client.get("/api/runs").json()) == 1
    assert seen == ["beacon"]


# ─── run detail assembly ───────────────────────────────────────────────────


def test_assemble_run_detail_links_everything():
    def proposal(pid, step, tool, args):
        return {
            "proposal_id": pid, "run_id": "run_1", "step_index": step, "tool": tool, "arguments": args,
            "rationale": "", "source": "agent", "status": "executed", "created_at": NOW,
        }

    manifest_body = {
        "manifest_id": "man_1", "grant_id": "grant_1", "run_id": "run_1", "principal": "maya",
        "tenant_id": "atlas", "workflow": "w", "snapshot_id": "S", "snapshot_digest": "d", "changes": [],
        "preconditions": {"authority_epoch": 1, "row_versions": {}, "fixture_generation": 1},
        "content_digest": "sha256:m", "status": "prepared", "created_at": NOW.isoformat(),
    }
    receipt = {
        "operation_id": "op_1", "idempotency_key": "k1", "grant_id": "grant_1", "run_id": "run_1",
        "manifest_id": "man_1", "manifest_digest": "sha256:m", "result": "committed",
        "enforcement_mode": "offline", "fixture_generation": 1, "created_at": NOW.isoformat(),
        "receipt_digest": "sha256:r",
    }
    approval = {
        "approval_id": "apr_1", "run_id": "run_1", "grant_id": "grant_1", "proposal_id": "p_apply",
        "tool": "apply_repair_manifest", "payload_digest": "sha256:m", "targets": ["O-2046"], "reason": "r",
        "requested_by": "maya", "requested_at": NOW.isoformat(), "expires_at": NOW.isoformat(),
        "state_constraints": {}, "status": "approved",
    }
    decision = {
        "decision_id": "d1", "run_id": "run_1", "proposal_id": "p_apply", "layer": "armoriq",
        "source": "armoriq.offline_simulation", "outcome": "hold", "simulated": True, "reason": "over $5000",
        "created_at": NOW.isoformat(),
    }
    rows = {
        "proposals": [
            proposal("p_prep", 0, "prepare_repair_manifest", {}),
            proposal("p_apply", 1, "apply_repair_manifest", {"manifest_id": "man_1", "idempotency_key": "k1"}),
            proposal("p_read", 2, "get_recovery_receipt", {"manifest_id": "man_1"}),
        ],
        "decisions": [decision],
        "manifests": [{**manifest_body, "status": "committed"}],
        "receipts": [receipt],
        "approvals": [approval],
        "prepared_events": [{"proposal_id": "p_prep", "data": {"manifest": {"manifest_id": "man_1"}}}],
    }
    detail = queries.assemble_run_detail(make_run(), make_grant(), rows)
    prep, apply_, read = detail["proposals"]
    assert prep["manifest"]["manifest_id"] == "man_1" and prep["manifest"]["status"] == "committed"
    assert prep["receipt"] is None and prep["decisions"] == []
    assert apply_["receipt"]["operation_id"] == "op_1"
    assert apply_["approval"]["approval_id"] == "apr_1"
    assert apply_["decisions"][0]["simulated"] is True
    assert read["manifest"] is None and read["receipt"] is None
    assert len(detail["approvals"]) == 1 and len(detail["receipts"]) == 1
    assert detail["run"]["run_id"] == "run_1" and detail["grant"]["grant_id"] == "grant_1"


def test_classify_order_conditions():
    snap = {"status": "paid", "total_cents": 100, "shipping_region": "EU"}
    damaged = {"status": "paid", "total_cents": 0, "shipping_region": "EU", "updated_by": "migration:fx"}
    later = {"status": "shipped", "total_cents": 100, "shipping_region": "EU", "updated_by": "fulfillment-svc"}
    assert queries.classify_order(snap, dict(snap, updated_by="x"), on_hold=False) == ("healthy", [])
    assert queries.classify_order(snap, damaged, on_hold=False) == ("damaged", ["total_cents"])
    assert queries.classify_order(snap, damaged, on_hold=True)[0] == "on_hold"
    assert queries.classify_order(snap, later, on_hold=False) == ("changed_after_snapshot", ["status"])
    assert queries.classify_order(snap, None, on_hold=False)[0] == "deleted_tombstoned"


# ─── approvals ─────────────────────────────────────────────────────────────


def make_approval(status="pending") -> ApprovalRecord:
    return ApprovalRecord(
        approval_id="apr_1", run_id="run_1", grant_id="grant_1", proposal_id="p1", tool="apply_repair_manifest",
        manifest_id="man_1", payload_digest="sha256:m", targets=["O-2046"], reason="High value",
        requested_by="maya", requested_at=NOW, expires_at=NOW + timedelta(minutes=10), state_constraints={},
        status=status,
    )


def test_approvals_list_includes_manifest_preview_and_validates_status(client, monkeypatch):
    seen = []
    monkeypatch.setattr(
        approvals, "list_for_tenant", lambda tenant, status=None: seen.append((tenant, status)) or [make_approval()],
        raising=False,
    )
    monkeypatch.setattr(queries, "manifest_body", lambda mid: {"manifest_id": mid, "changes": []})
    login(client, "dev")
    body = client.get("/api/approvals?status=pending").json()
    assert body[0]["manifest"]["manifest_id"] == "man_1" and seen == [("atlas", "pending")]
    assert client.get("/api/approvals?status=bogus").status_code == 400


def test_decide_is_reviewer_only_and_tenant_scoped(client, monkeypatch):
    monkeypatch.setattr(queries, "approval_tenant", lambda aid: "atlas")
    monkeypatch.setattr(queries, "manifest_body", lambda mid: None)
    decided = []

    def decide(aid, identity, decision, note=""):
        decided.append((aid, identity.identity_id, decision, note))
        return make_approval("approved")

    monkeypatch.setattr(approvals, "decide", decide, raising=False)
    login(client, "maya")
    response = client.post("/api/approvals/apr_1/decide", json={"decision": "approve"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "reviewer_required"
    login(client, "dev")
    assert client.post("/api/approvals/apr_1/decide", json={"decision": "maybe"}).status_code == 400
    ok = client.post("/api/approvals/apr_1/decide", json={"decision": "approve", "note": "looks right"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert decided == [("apr_1", "dev", "approve", "looks right")]
    monkeypatch.setattr(queries, "approval_tenant", lambda aid: "beacon")
    assert client.post("/api/approvals/apr_1/decide", json={"decision": "approve"}).status_code == 404


def test_decide_translates_domain_errors(client, monkeypatch):
    monkeypatch.setattr(queries, "approval_tenant", lambda aid: "atlas")

    def raising(exc):
        def _decide(*_a, **_k):
            raise exc
        return _decide

    login(client, "dev")
    monkeypatch.setattr(approvals, "decide", raising(ValueError("approval already decided")), raising=False)
    response = client.post("/api/approvals/apr_1/decide", json={"decision": "reject"})
    assert response.status_code == 409 and "already decided" in response.json()["error"]["message"]
    monkeypatch.setattr(approvals, "decide", raising(PermissionError("requester cannot approve")), raising=False)
    assert client.post("/api/approvals/apr_1/decide", json={"decision": "reject"}).status_code == 403


# ─── app state ─────────────────────────────────────────────────────────────


def test_app_state_is_scoped_to_session_tenant(client, monkeypatch):
    from rewindsafe.api import routes_app

    seen = []
    adapter = SimpleNamespace(
        app_state=lambda tenant: seen.append(tenant) or {"tenant": {"id": tenant}},
        protected_checks=lambda tenant: [],
    )
    monkeypatch.setattr(routes_app, "get_workflow_adapter", lambda: adapter)
    monkeypatch.setattr(grants, "current_generation", lambda: 4, raising=False)
    login(client, "sam")
    body = client.get("/api/app/state").json()
    assert body == {"tenant": {"id": "beacon"}, "fixture_generation": 4}
    assert client.get("/api/app/protected-checks").json() == []
    assert seen == ["beacon"]


# ─── admin ─────────────────────────────────────────────────────────────────


def test_reset_and_positive_control(client, monkeypatch):
    resets = []
    cancels = []
    monkeypatch.setattr(routes_admin.deps, "cancel_active_runs", lambda reason: cancels.append(reason) or 0)
    monkeypatch.setattr(routes_admin.deps, "active_run_ids", lambda: [])
    monkeypatch.setattr(routes_admin, "reset_fixture", lambda actor: resets.append(actor) or len(resets) + 10)
    counts = iter([0, 1])
    monkeypatch.setattr(routes_admin.mutators, "count_entries", lambda handler, **_: next(counts), raising=False)
    calls = []
    fake_admin = ModuleType("authority_admin")
    fake_admin.restore_access_grant = lambda *a, **k: calls.append((a, k))
    monkeypatch.setitem(sys.modules, "rewindsafe.workflows.rewindsafe.authority_admin", fake_admin)
    import rewindsafe.workflows.rewindsafe as wf

    monkeypatch.setattr(wf, "authority_admin", fake_admin, raising=False)

    @contextmanager
    def conn():
        yield SimpleNamespace(execute=lambda *_a, **_k: SimpleNamespace(fetchone=lambda: {"status": "active"}))

    monkeypatch.setattr(routes_admin.db, "connection", conn)
    login(client, "maya")
    assert client.post("/api/admin/reset").json() == {"generation": 11}
    body = client.post("/api/admin/positive-control").json()
    assert body["handler_entries_before"] == 0 and body["handler_entries_after"] == 1
    assert body["grant_status_after"] == "active"
    assert resets == ["maya", "maya"]  # positive control always resets afterwards
    assert len(cancels) == 2  # live workers are stopped before each fixture change
    assert calls[0][0][:2] == ("atlas", "AG-77") and calls[0][1]["via"] == "operator_admin"


def test_positive_control_resets_even_when_handler_fails(client, monkeypatch):
    resets = []
    monkeypatch.setattr(routes_admin.deps, "cancel_active_runs", lambda reason: 0)
    monkeypatch.setattr(routes_admin.deps, "active_run_ids", lambda: [])
    monkeypatch.setattr(routes_admin, "reset_fixture", lambda actor: resets.append(actor) or 2)
    monkeypatch.setattr(routes_admin.mutators, "count_entries", lambda *_a, **_k: 0, raising=False)
    fake_admin = ModuleType("authority_admin")

    def fail(*_a, **_k):
        raise RuntimeError("boom")

    fake_admin.restore_access_grant = fail
    import rewindsafe.workflows.rewindsafe as wf

    monkeypatch.setattr(wf, "authority_admin", fake_admin, raising=False)
    monkeypatch.setitem(sys.modules, "rewindsafe.workflows.rewindsafe.authority_admin", fake_admin)
    local = TestClient(create_app(run_startup=False), raise_server_exceptions=False)
    login(local, "maya")
    assert local.post("/api/admin/positive-control").status_code == 500
    assert resets == ["maya"]


# ─── SSE route ─────────────────────────────────────────────────────────────


@pytest.fixture()
def fast_sse(monkeypatch):
    import functools

    original = sse.stream_events
    monkeypatch.setattr(sse, "stream_events", functools.partial(original, poll_interval=0.01, close_grace=0.05))


def stored_events(seqs, finish_at=None):
    items = [make_event(s, "run.finished" if s == finish_at else "agent.note") for s in seqs]

    def list_events(run_id, after_seq=0, limit=500):
        return [e for e in items if e.seq > after_seq]

    return list_events


def test_sse_framing_resume_and_close(client, monkeypatch, fast_sse):
    monkeypatch.setattr(queries, "get_run_with_tenant", lambda rid: (make_run(), "atlas"))
    monkeypatch.setattr(queries, "finished_seq", lambda rid: None)
    monkeypatch.setattr(routes_runs.events, "list_events", stored_events([1, 2, 3], finish_at=3))
    login(client, "maya")
    with client.stream("GET", "/api/runs/run_1/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    frames = [f for f in body.split("\n\n") if f.startswith("id:")]
    assert [f.splitlines()[0] for f in frames] == ["id: 1", "id: 2", "id: 3"]
    assert all(f.splitlines()[1] == "event: run_event" and f.splitlines()[2].startswith("data: {") for f in frames)
    # Last-Event-ID resumes after the given sequence.
    with client.stream("GET", "/api/runs/run_1/events", headers={"Last-Event-ID": "2"}) as response:
        resumed = "".join(response.iter_text())
    assert "id: 3" in resumed and "id: 2\n" not in resumed and "id: 1\n" not in resumed
    # ?after= works too and the later of the two wins.
    with client.stream("GET", "/api/runs/run_1/events?after=1", headers={"Last-Event-ID": "0"}) as response:
        assert "id: 2" in "".join(response.iter_text())


def test_sse_returns_204_when_client_already_saw_run_finished(client, monkeypatch):
    monkeypatch.setattr(queries, "get_run_with_tenant", lambda rid: (make_run(), "atlas"))
    monkeypatch.setattr(queries, "finished_seq", lambda rid: 3)
    login(client, "maya")
    assert client.get("/api/runs/run_1/events", headers={"Last-Event-ID": "3"}).status_code == 204


def test_sse_is_tenant_scoped(client, monkeypatch):
    monkeypatch.setattr(queries, "get_run_with_tenant", lambda rid: (make_run(), "atlas"))
    login(client, "sam")
    assert client.get("/api/runs/run_1/events").status_code == 404
    client.post("/api/session/logout")
    assert client.get("/api/runs/run_1/events").status_code == 401


# ─── verification jobs ─────────────────────────────────────────────────────


def test_verification_runs_one_at_a_time(client, monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []

    def run_suite(verification_id):
        calls.append(verification_id)
        started.set()
        release.wait(5)
        return {"status": "passed"}

    suite = SimpleNamespace(run_suite=run_suite, get=lambda vid: None, latest=lambda: None)
    monkeypatch.setattr(verification_jobs, "_suite", lambda: suite)
    login(client, "maya")
    first = client.post("/api/verification/run")
    assert first.status_code == 200
    vid = first.json()["verification_id"]
    assert started.wait(5)
    second = client.post("/api/verification/run")
    assert second.status_code == 409 and second.json()["error"]["code"] == "verification_running"
    running = client.get(f"/api/verification/{vid}").json()
    assert running["status"] == "running"
    assert client.get("/api/verification/latest").json() is None
    release.set()
    for _ in range(100):
        if verification_jobs.current_id() is None:
            break
        threading.Event().wait(0.02)
    assert verification_jobs.current_id() is None
    assert client.get("/api/verification/ver_missing").status_code == 404
    assert client.post("/api/verification/run").status_code == 200  # free again
    assert len(calls) >= 1
    release.set()


def test_verification_crash_releases_lock_and_records_failure(monkeypatch):
    recorded = []
    monkeypatch.setattr(verification_jobs, "_mark_failed", lambda vid, err: recorded.append((vid, err)))

    def crash(_vid):
        raise RuntimeError("suite exploded")

    monkeypatch.setattr(verification_jobs, "_suite", lambda: SimpleNamespace(run_suite=crash))
    vid = verification_jobs.start()
    for _ in range(100):
        if verification_jobs.current_id() is None:
            break
        threading.Event().wait(0.02)
    assert verification_jobs.current_id() is None
    assert recorded and recorded[0][0] == vid and "suite exploded" in recorded[0][1]


# ─── static frontend ───────────────────────────────────────────────────────


@pytest.fixture()
def tmp_path():
    with tempfile.TemporaryDirectory() as name:
        yield Path(name)


def test_static_spa_fallback(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("top secret")
    monkeypatch.setattr(app_module, "DIST_DIR", dist)
    local = TestClient(create_app(run_startup=False))
    assert local.get("/").text == "<html>spa</html>"
    assert local.get("/runs/run_1").text == "<html>spa</html>"  # client-side route
    js = local.get("/assets/app.js")
    assert js.text == "console.log(1)" and "javascript" in js.headers["content-type"]
    assert local.get("/api/nope").json()["error"]["code"] == "not_found"
    assert "top secret" not in local.get("/..%2fsecret.txt").text
    assert "top secret" not in local.get("/%2e%2e/secret.txt").text


def test_static_missing_dist_is_json_404(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DIST_DIR", tmp_path / "absent")
    response = TestClient(create_app(run_startup=False)).get("/")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


def test_typed_runtime_errors_keep_their_codes(client, monkeypatch):
    monkeypatch.setattr(queries, "approval_tenant", lambda aid: "atlas")
    login(client, "dev")
    cases = [
        (approvals.ApprovalError("not_pending", "This approval is already approved."), 409, "not_pending"),
        (approvals.ApprovalError("separation_of_duties", "Requester cannot approve."), 403, "separation_of_duties"),
        (approvals.ApprovalError("expired", "Expired."), 409, "expired"),
        (approvals.ApprovalNotFound("apr_x"), 404, "approval_not_found"),
    ]
    for exc, status_code, code in cases:
        def _decide(*_a, _exc=exc, **_k):
            raise _exc

        monkeypatch.setattr(approvals, "decide", _decide, raising=False)
        response = client.post("/api/approvals/apr_1/decide", json={"decision": "approve"})
        assert response.status_code == status_code and response.json()["error"]["code"] == code


def test_grant_not_found_is_404(client, monkeypatch):
    def missing(_gid):
        raise grants.GrantNotFound("grant nope not found")

    monkeypatch.setattr(grants, "load", missing, raising=False)
    login(client, "maya")
    assert client.get("/api/grants/nope").status_code == 404


# ─── live evidence, metrics split, draft auto_reset ────────────────────────


def test_evidence_live_sanitizes_and_includes_readiness(client, monkeypatch, tmp_path):
    import json as _json

    from rewindsafe.api import evidence

    (tmp_path / "gate-a-2026-10-07T00-00-00Z.json").write_text(_json.dumps({
        "probes": [{"probe": "allow", "outcome": "allow", "token": "SECRETTOKEN", "reason": "key ak_live_abcdefghij1234"}],
    }))
    (tmp_path / "gate-a-early-live-2026-10-07.md").write_text("early note")
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path)
    monkeypatch.setattr(evidence, "_readiness", lambda: {"state": "verified"})
    body = client.get("/api/evidence/live").json()
    assert body["gate_a_early"] == "early note" and body["injection_eval"] is None
    assert body["readiness"] == {"state": "verified"}
    text = _json.dumps(body)
    assert "SECRETTOKEN" not in text and "ak_live_abcdefghij" not in text
    assert body["gate_a"]["probes"][0]["outcome"] == "allow"


def test_evidence_live_handles_missing_files(client, monkeypatch, tmp_path):
    from rewindsafe.api import evidence

    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path)
    monkeypatch.setattr(evidence, "_readiness", lambda: None)
    body = client.get("/api/evidence/live").json()
    assert body == {"gate_a": None, "gate_a_early": None, "injection_eval": None, "readiness": None}


def test_metrics_exposes_armoriq_split(client, monkeypatch):
    from rewindsafe.api import metrics as metrics_mod

    login(client, "maya")
    metric_tenants = []
    monkeypatch.setattr(
        routes_system.receipts,
        "global_metrics",
        lambda *, tenant_id=None: (metric_tenants.append(tenant_id) or {"runs": 1, "armoriq_latency_ms": {}}),
    )
    split = {"plan_binding": {"count": 2}, "enforce": {"p50": 850.0, "p95": 900.0, "count": 3},
             "issuance": {"p50": 4700.0, "p95": 4700.0, "count": 1}}
    split_tenants = []
    monkeypatch.setattr(metrics_mod, "armoriq_split", lambda *, tenant_id=None: (split_tenants.append(tenant_id) or (split, False)))
    body = client.get("/api/metrics").json()
    assert body["armoriq"] == split and body["simulated"] is False
    assert metric_tenants == ["atlas"] and split_tenants == ["atlas"]


def test_draft_auto_reset_when_dirty(client, monkeypatch):
    from rewindsafe.api import routes_admin

    login(client, "maya")
    state = {"dirty": True}
    adapter = SimpleNamespace(
        scenarios=lambda: [make_scenario("clean", 1)],
        fixture_status=lambda: {"dirty": state["dirty"], "repaired_orders": ["O-2041"], "note": "x"},
    )
    monkeypatch.setattr(routes_runs, "get_workflow_adapter", lambda: adapter)
    monkeypatch.setattr(grants, "create_draft", lambda *_: make_grant(), raising=False)
    resets = []

    def fake_reset(actor):
        resets.append(actor)
        state["dirty"] = False
        return 9

    monkeypatch.setattr(routes_admin, "safe_reset", fake_reset)
    body = client.post("/api/grants/draft", json={"scenario_id": "clean"}).json()
    assert body["fixture"]["dirty"] is True and body["fixture_reset"] is False and not resets
    state["dirty"] = True
    body = client.post("/api/grants/draft", json={"scenario_id": "clean", "auto_reset": True}).json()
    assert resets == ["maya"] and body["fixture_reset"] is True and body["fixture"]["dirty"] is False
