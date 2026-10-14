"""Demo-only admin routes: reachable for a demo operator in development, absent in production."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rewindsafe import config
from rewindsafe.api import auth, routes_admin
from rewindsafe.api.app import create_app
from rewindsafe.api.errors import ApiError
from rewindsafe.contracts import Identity

DEMO_OPERATOR = Identity(
    identity_id="maya", name="Maya", email="maya@example.test", role="operator",
    tenant_id="atlas", title="Operator", initials="MA", color="#123456",
)
DEMO_ROUTES = ("/api/admin/reset", "/api/admin/positive-control")


class Reached(Exception):
    """Raised by the stubbed handler hook to prove a request got past the guard into the handler."""


@pytest.fixture()
def environment(monkeypatch):
    def use(name: str, auth_mode: str = "demo") -> None:
        settings = config.Settings(_env_file=None, REWINDSAFE_ENV=name, REWINDSAFE_AUTH_MODE=auth_mode)
        monkeypatch.setattr(auth, "get_settings", lambda: settings)

    return use


@pytest.fixture()
def handler_entries(monkeypatch):
    entries = []

    def cancel_active_runs(reason):  # first call made by both demo handlers
        entries.append(reason)
        raise Reached(reason)

    monkeypatch.setattr(routes_admin.deps, "cancel_active_runs", cancel_active_runs)
    return entries


def make_client(signed_in: bool) -> TestClient:
    app = create_app(run_startup=False)
    if signed_in:
        app.dependency_overrides[auth.current_identity] = lambda: DEMO_OPERATOR
    return TestClient(app)


def test_development_demo_operator_reaches_the_demo_routes(environment, handler_entries):
    environment("development")
    client = make_client(signed_in=True)
    for path in DEMO_ROUTES:
        with pytest.raises(Reached):  # TestClient re-raises the stub's error once the handler was entered
            client.post(path)
    assert handler_entries == [routes_admin.RESET_REASON, "Positive control in progress"]


@pytest.mark.parametrize("path", DEMO_ROUTES)
@pytest.mark.parametrize("signed_in", [True, False], ids=["demo-operator", "anonymous"])
def test_production_has_no_demo_routes_whoever_is_signed_in(environment, handler_entries, path, signed_in):
    environment("production")
    response = make_client(signed_in).post(path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert handler_entries == []


def test_production_refuses_the_guard_when_called_directly(environment):
    # routes_runs and routes_verification call require_demo_operator directly, not as a route dependency
    environment("production")
    with pytest.raises(ApiError) as refused:
        auth.require_demo_operator(DEMO_OPERATOR)
    assert refused.value.status_code == 404


def test_oidc_sign_in_never_passes_the_demo_guard(environment):
    environment("development", auth_mode="oidc")
    with pytest.raises(ApiError) as refused:
        auth.require_demo_operator(DEMO_OPERATOR)
    assert refused.value.status_code == 403 and refused.value.code == "demo_only"
