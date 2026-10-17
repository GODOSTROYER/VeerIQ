"""Judge walkthrough helpers: the full-rollback preview (read-only) and the MCP install endpoint."""

from __future__ import annotations

from pathlib import Path
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from rewindsafe.api import routes_judge
from rewindsafe.api.app import create_app
from rewindsafe.contracts import GrantStatus, TaskGrant
from rewindsafe.workflows.rewindsafe import fixture as fx
from rewindsafe.workflows.rewindsafe import queries as wq


def _by_entity(preview: dict) -> dict[str, dict]:
    return {c["entity"]: c for c in preview["changes"]}


def test_full_rollback_preview_repairs_damage_and_reverses_every_later_decision(fresh):
    preview = wq.full_rollback_preview(fx.TENANT_ATLAS)
    changes = _by_entity(preview)

    assert {e for e, c in changes.items() if c["verdict"] == "good"} == {"O-2041", "O-2042", "O-2046"}
    assert changes["O-2043"]["kind"] == "later_decision_reverted"  # shipped -> processing
    assert changes["O-2043"]["after_rollback"] == {"status": "processing"}
    assert changes["O-2044"]["kind"] == "erased_record_returns"
    assert changes["C-1003"]["kind"] == "erased_record_returns"
    assert changes["AG-77"]["kind"] == "access_reenabled"
    assert preview["repaired"] == 3 and preview["harmed"] == 4
    assert "B-3002" not in changes  # another tenant's rows are never part of this tenant's preview


def test_full_rollback_preview_writes_nothing(fresh):
    before = wq.app_state(fx.TENANT_ATLAS)
    wq.full_rollback_preview(fx.TENANT_ATLAS)
    after = wq.app_state(fx.TENANT_ATLAS)
    assert before["orders"] == after["orders"]
    assert before["access_grants"] == after["access_grants"]
    assert before["deleted"] == after["deleted"]
    assert after["beacon"]["untouched"]


def test_full_rollback_preview_other_tenant_sees_only_its_own_damage(fresh):
    changes = _by_entity(wq.full_rollback_preview(fx.TENANT_BEACON))
    assert set(changes) == {"B-3002"}
    assert changes["B-3002"]["verdict"] == "good"


# ─── MCP install ───────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _grant(status: GrantStatus) -> TaskGrant:
    return TaskGrant(
        grant_id="grant_judge",
        workflow="rewindsafe.order_repair",
        scenario_id="poisoned",
        principal="maya",
        principal_email="nova.reyes@atlas.example",
        tenant_id="atlas",
        purpose="repair",
        allowed_tools=["inspect_snapshot"],
        resources={"order": ["O-2041"]},
        status=status,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        fixture_generation=1,
        grant_digest="sha256:x",
    )


@pytest.fixture()
def client() -> TestClient:
    c = TestClient(create_app(run_startup=False))
    assert c.post("/api/session", json={"identity_id": "maya"}).status_code == 200
    return c


def test_mcp_install_for_an_active_grant(client, monkeypatch):
    monkeypatch.setattr(routes_judge, "load_grant_for", lambda identity, gid: _grant(GrantStatus.ACTIVE))
    response = client.get("/api/judge/mcp-install/grant_judge")
    body = response.json()
    placeholder = "<path-to-your-VeerIQ-checkout>"
    args = ["run", "--directory", f"{placeholder}/backend", "python", "-m", "rewindsafe.mcp_server", "--grant", "grant_judge"]
    assert body["mode"] == "local-checkout"
    assert body["grant_id"] == "grant_judge"
    assert body["claude_code"].startswith(f"claude mcp add veeriq-recovery -- uv run --directory {placeholder}/backend")
    assert body["claude_code"].endswith("--grant grant_judge")
    assert body["claude_desktop"] == {"mcpServers": {"veeriq-recovery": {"command": "uv", "args": args}}}
    assert "--grant grant_judge --http" in body["local_http"]
    assert body["setup_steps"]
    assert "restore_access_grant" in body["tools"]
    # No server filesystem path leaks.
    backend_dir = str(Path(routes_judge.__file__).resolve().parents[2])
    assert backend_dir not in response.text
    assert backend_dir.replace("\\", "/") not in response.text


def test_mcp_install_refuses_a_draft_grant(client, monkeypatch):
    monkeypatch.setattr(routes_judge, "load_grant_for", lambda identity, gid: _grant(GrantStatus.DRAFT))
    response = client.get("/api/judge/mcp-install/grant_judge")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "grant_not_active"


def test_mcp_install_needs_a_session():
    response = TestClient(create_app(run_startup=False)).get("/api/judge/mcp-install/grant_judge")
    assert response.status_code == 401
