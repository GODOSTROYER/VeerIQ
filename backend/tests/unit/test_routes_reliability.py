"""Authenticated reliability evidence endpoint tests; no database or live provider."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rewindsafe.api import routes_reliability, routes_session
from rewindsafe.api.errors import install_error_handlers


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(routes_session.router)
    app.include_router(routes_reliability.router)
    return TestClient(app)


def test_latest_reliability_requires_authentication_and_returns_safe_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_reliability, "EVIDENCE_DIR", tmp_path)
    path = tmp_path / "reliability-20261012T000000Z.json"
    original = {
        "requested_trials": 1,
        "updated_at": "2026-10-12T00:00:00Z",
        "models": ["groq/test"],
        "briefings": ["task_only"],
        "summary": {},
        "api_key": "gsk_" + "x" * 32,
        "trials": [
            {
                "briefing": "task_only",
                "model": "groq/test",
                "trial": 1,
                "status": "completed",
                "outcome": "succeeded",
                "completed": True,
                "failed": False,
                "attempted_restore": 0,
                "attempted_cross_tenant": 0,
                "forbidden_attempts": [],
                "forbidden_effects": 0,
                "failure": "provider echoed gsk_" + "x" * 32,
            }
        ],
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    client = _client()

    assert client.get("/api/evidence/reliability").status_code == 401
    assert client.post("/api/session", json={"identity_id": "maya"}).status_code == 200
    response = client.get("/api/evidence/reliability")

    assert response.status_code == 200
    body = response.json()
    assert body["requested_trials"] == 1 and body["finished_at"] == original["updated_at"]
    assert body["summary"]["task_only|groq/test"]["unknown_safety_trials"] == 1
    assert body["summary"]["task_only|groq/test"]["forbidden_effects"] is None
    assert body["trials"][0]["failure_cause"] == "safety_evidence_unavailable"
    assert "gsk_" + "x" * 32 not in response.text
    # Serving the old artifact does not rewrite or erase its raw evidence.
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["trials"][0]["forbidden_effects"] == 0
    assert "evidence_complete" not in saved["trials"][0]

    catalog = client.get("/api/evidence/reliability/catalog")
    assert catalog.status_code == 200
    assert catalog.json() == {
        "artifacts": [
            {
                "file": path.name,
                "requested_trials": 1,
                "recorded_trials": 1,
                "finished_at": original["updated_at"],
            }
        ]
    }
    selected = client.get("/api/evidence/reliability", params={"file": path.name})
    assert selected.status_code == 200 and selected.json()["file"] == path.name
    assert client.get("/api/evidence/reliability", params={"file": "../../secrets.json"}).status_code == 404


def test_latest_reliability_returns_not_found_when_no_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_reliability, "EVIDENCE_DIR", tmp_path)
    client = _client()
    client.post("/api/session", json={"identity_id": "maya"})
    response = client.get("/api/evidence/reliability")
    assert response.status_code == 404
