"""W3 unit tests for the MCP server surface (stubbed bridge; no DB, no network)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import ClassVar

import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from rewindsafe import mcp_server


class StubBridge:
    calls: ClassVar[list[tuple[str, dict]]] = []

    def __init__(self, grant_id=None, *, run_id=None, gateway=None) -> None:
        self.run_id = run_id or "run_x"

    def specs(self):
        return {}

    def call(self, tool, args):
        StubBridge.calls.append((tool, args))
        return {"status": "executed", "tool": tool}

    def close(self):
        pass


@pytest.fixture()
def server(monkeypatch):
    StubBridge.calls = []
    monkeypatch.setattr(mcp_server, "RunBridge", StubBridge)
    return mcp_server.build_server("grant_x")


def test_mirrors_the_six_tools(server):
    tools = asyncio.run(server.list_tools())
    assert sorted(t.name for t in tools) == sorted(mcp_server.TOOL_NAMES)
    by = {t.name: t for t in tools}
    schema = (
        by["apply_repair_manifest"].input_schema
        if hasattr(by["apply_repair_manifest"], "input_schema")
        else by["apply_repair_manifest"].inputSchema
    )
    assert set(schema["required"]) == {"manifest_id", "manifest_digest", "idempotency_key"}


def test_every_call_goes_through_the_bridge(server):
    asyncio.run(server.call_tool("compare_current", {"tenant_id": "atlas", "order_ids": ["O-2041"]}))
    asyncio.run(server.call_tool("get_recovery_receipt", {"manifest_id": "mf_1"}))
    asyncio.run(
        server.call_tool("restore_access_grant", {"tenant_id": "atlas", "grant_id": "AG-77", "reason": "x"})
    )
    assert [c[0] for c in StubBridge.calls] == [
        "compare_current",
        "get_recovery_receipt",
        "restore_access_grant",
    ]
    # None-valued optional arguments are dropped, never sent to the dispatcher
    assert StubBridge.calls[1][1] == {"manifest_id": "mf_1"}


def test_main_refuses_unknown_run(monkeypatch, capsys):
    def boom(*a, **k):
        raise KeyError("run 'nope' not found")

    monkeypatch.setattr(mcp_server, "build_server", boom)
    assert mcp_server.main(["--grant", "nope"]) == 2
    assert "not found" in capsys.readouterr().err
    assert json.dumps({}) == "{}"


# ─── real bridge (offline gateway, disposable DB): the MCP path must bind its own plan ───


def _authorized_grant(scenario_id: str):
    import rewindsafe.workflows.rewindsafe.adapter  # noqa: F401
    from rewindsafe.runtime import grants
    from rewindsafe.runtime.adapter import get_adapter
    from rewindsafe.runtime.identities import get_identity

    adapter = get_adapter("rewindsafe.order_repair")
    maya = get_identity("maya")
    scenario = next(s for s in adapter.scenarios() if s.scenario_id == scenario_id)
    return grants.authorize(grants.create_draft(adapter, scenario, maya).grant_id, maya)


def test_bridge_creates_its_own_run_binds_a_plan_and_executes_reads(fresh):
    from rewindsafe.agent import get_run
    from rewindsafe.runtime import events, grants
    from rewindsafe.runtime.armoriq_gateway import OfflineSimulatedGateway

    grant = _authorized_grant("poisoned")
    bridge = mcp_server.RunBridge(grant.grant_id, gateway=OfflineSimulatedGateway())  # fresh gateway = other process
    run = get_run(bridge.run_id)
    assert run.planner == "mcp-client" and run.plan is not None and run.status.value == "executing"
    assert "plan.bound" in [e.type for e in events.list_events(bridge.run_id, limit=200)]
    snap = grant.source_constraints.get("snapshot_id") or grant.resources["snapshot"][0]
    result = bridge.call("inspect_snapshot", {"snapshot_id": snap, "tenant_id": grant.tenant_id})
    assert result  # allowed and executed, not "unavailable"
    with pytest.raises(mcp_server.ToolError):
        bridge.call(
            "restore_access_grant", {"tenant_id": grant.tenant_id, "grant_id": "AG-77", "reason": "runbook says so"}
        )
    bridge.close()
    bridge.close()  # idempotent
    done = get_run(bridge.run_id)
    assert done.status.value in {"blocked", "failed", "cancelled", "partially_succeeded", "succeeded"}
    assert grants.load(grant.grant_id).status.value == "exhausted"
    with pytest.raises(mcp_server.ToolError):
        bridge.call("inspect_snapshot", {"snapshot_id": snap, "tenant_id": grant.tenant_id})


def test_bridge_refuses_inactive_or_busy_grants(fresh):
    from rewindsafe.runtime import grants
    from rewindsafe.runtime.armoriq_gateway import OfflineSimulatedGateway

    grant = _authorized_grant("clean")
    first = mcp_server.RunBridge(grant.grant_id, gateway=OfflineSimulatedGateway())
    with pytest.raises(mcp_server.ToolError, match="already using"):
        mcp_server.RunBridge(grant.grant_id, gateway=OfflineSimulatedGateway())
    first.close()
    with pytest.raises(mcp_server.ToolError, match="not active"):
        mcp_server.RunBridge(grant.grant_id, gateway=OfflineSimulatedGateway())
    assert grants.load(grant.grant_id).status.value == "exhausted"


# ─── HTTP transport: loopback-only without a token; bearer token on every request otherwise ───

TOKEN = "s3cret-mcp-token"
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}
COMPARE = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {"name": "compare_current", "arguments": {"tenant_id": "atlas", "order_ids": ["O-2041"]}},
}


def _run_http(monkeypatch, host: str, token: str):
    """main() in --http mode with a stub bridge; uvicorn.run is captured instead of binding a socket."""
    served = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: served.append((app, kw)))
    monkeypatch.setattr(mcp_server.signal, "signal", lambda *a, **k: None)  # keep pytest's signal handlers
    monkeypatch.setattr(mcp_server, "load_settings", lambda: SimpleNamespace(mcp_token=token))
    monkeypatch.setattr(mcp_server, "RunBridge", StubBridge)
    StubBridge.calls = []
    code = mcp_server.main(["--grant", "grant_x", "--http", "--host", host])
    return code, served


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::", "mcp.example.test"])
def test_http_refuses_non_loopback_host_without_token(monkeypatch, capsys, host):
    served = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: served.append(app))
    monkeypatch.setattr(mcp_server, "load_settings", lambda: SimpleNamespace(mcp_token=""))
    monkeypatch.setattr(mcp_server, "build_server", lambda *a, **k: pytest.fail("built a run first"))
    assert mcp_server.main(["--grant", "grant_x", "--http", "--host", host]) == 2
    assert "REWINDSAFE_MCP_TOKEN" in capsys.readouterr().err
    assert served == []


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_http_on_loopback_is_still_allowed_without_token(monkeypatch, host):
    code, served = _run_http(monkeypatch, host, token="")
    assert code == 0 and len(served) == 1
    app, kwargs = served[0]
    assert kwargs["host"] == host and not isinstance(app, mcp_server.BearerTokenMiddleware)


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_http_with_token_rejects_bad_credentials_before_any_tool_runs(monkeypatch, host):
    code, served = _run_http(monkeypatch, host, token=TOKEN)
    assert code == 0
    app = served[0][0]
    assert isinstance(app, mcp_server.BearerTokenMiddleware)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        for auth_header in (None, f"Basic {TOKEN}", "Bearer", "Bearer wrong-token"):
            headers = dict(MCP_HEADERS, **({} if auth_header is None else {"Authorization": auth_header}))
            assert client.post("/mcp", json=COMPARE, headers=headers).status_code == 401, auth_header
        assert StubBridge.calls == []
        good = dict(MCP_HEADERS, Authorization=f"Bearer {TOKEN}")
        init = client.post("/mcp", json=INITIALIZE, headers=good)
        assert init.status_code == 200
        good["mcp-session-id"] = init.headers["mcp-session-id"]
        assert client.post("/mcp", json=COMPARE, headers=good).status_code == 200
    assert StubBridge.calls == [("compare_current", {"tenant_id": "atlas", "order_ids": ["O-2041"]})]


@pytest.mark.parametrize(
    ("header", "accepted"),
    [
        ("Bearer s3cret", True),
        ("bearer s3cret", True),
        (None, False),
        ("", False),
        ("s3cret", False),
        ("Basic s3cret", False),
        ("Bearer", False),
        ("Bearer wrong", False),
        ("Bearer s3cre", False),
        ("Bearer s3cret-extra", False),
    ],
)
def test_bearer_check_accepts_only_the_configured_token(header, accepted):
    assert mcp_server.bearer_token_valid(header, "s3cret") is accepted
    assert mcp_server.bearer_token_valid("Bearer anything", "") is False  # no token configured: never accepts


def _guarded(calls):
    async def inner(scope, receive, send):
        calls.append(scope["path"])
        await PlainTextResponse("ok")(scope, receive, send)

    return mcp_server.BearerTokenMiddleware(inner, "s3cret")


@pytest.mark.parametrize("auth_header", [None, "Basic s3cret", "Bearer", "s3cret", "Bearer wrong"])
def test_middleware_answers_401_before_the_app_runs(auth_header):
    calls = []
    headers = {} if auth_header is None else {"Authorization": auth_header}
    response = TestClient(_guarded(calls)).get("/mcp", headers=headers)
    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthenticated"
    assert calls == []


def test_middleware_passes_the_right_token_through():
    calls = []
    response = TestClient(_guarded(calls)).get("/mcp", headers={"Authorization": "Bearer s3cret"})
    assert response.status_code == 200 and calls == ["/mcp"]


def test_middleware_never_guards_with_an_empty_token():
    with pytest.raises(ValueError):
        mcp_server.BearerTokenMiddleware(lambda *a: None, "")
