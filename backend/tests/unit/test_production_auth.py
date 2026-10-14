from __future__ import annotations

import base64
import hashlib
import json
import time
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from rewindsafe import config
from rewindsafe.api import observability, oidc, routes_oidc, routes_session
from rewindsafe.api.errors import ApiError, install_error_handlers
from rewindsafe.api.observability import BoundedWindowLimiter, ObservabilityMiddleware


def _b64(value: int) -> str:
    return base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()


def _mapping(identity_id: str = "operator-1", role: str = "operator", tenant_id: str = "atlas") -> dict[str, str]:
    return {
        "identity_id": identity_id,
        "name": "Operator One",
        "email": "operator@example.test",
        "role": role,
        "tenant_id": tenant_id,
        "title": "Operator",
        "initials": "O1",
        "color": "#123456",
    }


def test_oidc_subject_mapping_is_server_side_and_requires_distinct_ids(monkeypatch):
    settings = config.Settings(
        REWINDSAFE_AUTH_MODE="oidc",
        REWINDSAFE_OIDC_SUBJECTS_JSON=json.dumps({"issuer-subject-a": _mapping(), "issuer-subject-b": _mapping()}),
    )
    with pytest.raises(config.ConfigurationError, match="distinct identity_id"):
        settings.oidc_subject_mappings()

    mapped = config.Settings(
        REWINDSAFE_AUTH_MODE="oidc",
        REWINDSAFE_OIDC_SUBJECTS_JSON=json.dumps({"issuer-subject": _mapping(role="reviewer")}),
    ).oidc_subject_mappings()
    monkeypatch.setattr(oidc, "get_settings", lambda: SimpleNamespace(oidc_subject_mappings=lambda: mapped))
    identity = oidc._identity_for_subject("issuer-subject")
    assert identity.role == "reviewer" and identity.tenant_id == "atlas"
    with pytest.raises(ApiError, match="not mapped"):
        oidc._identity_for_subject("unconfigured-subject")


def test_oidc_settings_fail_closed_with_clear_configuration_gaps():
    settings = config.Settings(_env_file=None, REWINDSAFE_AUTH_MODE="oidc")
    with pytest.raises(config.ConfigurationError, match="REWINDSAFE_OIDC_ISSUER"):
        settings.validate_startup()


def test_frontend_auth_contract_and_demo_impersonation_disabled_in_oidc(monkeypatch):
    settings = SimpleNamespace(auth_mode="oidc")
    monkeypatch.setattr(oidc, "get_settings", lambda: settings)
    monkeypatch.setattr(routes_session.auth, "get_settings", lambda: settings)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(routes_oidc.router)
    app.include_router(routes_session.router)
    client = TestClient(app)
    config_response = client.get("/api/auth/config")
    assert config_response.status_code == 200
    assert config_response.json() == {"mode": "oidc", "login_url": "/api/auth/login"}
    assert client.get("/api/identities").status_code == 401
    assert client.post("/api/session", json={"identity_id": "maya"}).status_code == 403


def test_id_token_requires_valid_issuer_audience_and_nonce(monkeypatch):
    issuer = "https://idp.example.test"
    client_id = "veeriq-client"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private_key.public_key().public_numbers()
    jwks = {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": "key-1", "n": _b64(public.n), "e": _b64(public.e)}]}
    settings = SimpleNamespace(oidc_issuer=issuer, oidc_client_id=client_id, oidc_client_secret="client-secret",
                               oidc_redirect_uri=issuer + "/callback")
    metadata = {"issuer": issuer, "token_endpoint": issuer + "/token", "jwks_uri": issuer + "/jwks"}
    monkeypatch.setattr(oidc, "get_settings", lambda: settings)
    monkeypatch.setattr(oidc, "discovery", lambda _: metadata)

    class JsonResponse:
        def __init__(self, value): self.value = value
        def raise_for_status(self): pass
        def json(self): return self.value

    monkeypatch.setattr(oidc.httpx, "get", lambda *_a, **_k: JsonResponse(jwks))

    def exchange(claims):
        token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "key-1"})
        monkeypatch.setattr(oidc.httpx, "post", lambda *_a, **_k: JsonResponse({"id_token": token}))
        return oidc._exchange_code("code", "verifier", "expected-nonce")

    base_claims = {"iss": issuer, "aud": client_id, "sub": "external-sub", "exp": int(time.time()) + 300,
                   "iat": int(time.time()), "nonce": "expected-nonce"}
    assert exchange(base_claims)["sub"] == "external-sub"
    for change in ({"aud": "another-client"}, {"iss": "https://attacker.example"}, {"nonce": "wrong"}):
        with pytest.raises(ApiError, match="token validation"):
            exchange(base_claims | change)


def test_login_request_uses_one_time_state_nonce_and_s256_pkce(monkeypatch):
    issuer = "https://identity.example.test/tenant"
    settings = SimpleNamespace(auth_mode="oidc", oidc_issuer=issuer, oidc_client_id="veeriq-web",
                               oidc_redirect_uri="https://app.example.test/api/auth/callback")
    monkeypatch.setattr(oidc, "get_settings", lambda: settings)
    monkeypatch.setattr(oidc, "discovery", lambda _issuer: {
        "authorization_endpoint": "https://identity.example.test/authorize",
    })
    stored = []
    monkeypatch.setattr(oidc, "_save_login_state", lambda state, nonce, verifier: stored.append((state, nonce, verifier)))
    url = oidc.begin_login()
    query = parse_qs(urlsplit(url).query)
    assert query["response_type"] == ["code"]
    assert query["state"] == [stored[0][0]] and query["nonce"] == [stored[0][1]]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [oidc._b64url(hashlib.sha256(stored[0][2].encode()).digest())]


def test_oidc_callback_creates_opaque_secure_session_from_admin_mapping(monkeypatch):
    mapping = {"real-issuer-sub": _mapping()}
    settings = SimpleNamespace(
        auth_mode="oidc",
        oidc_subject_mappings=lambda: mapping,
        oidc_app_origin="https://app.example.test",
    )
    monkeypatch.setattr(oidc, "get_settings", lambda: settings)
    monkeypatch.setattr(oidc, "_consume_login_state", lambda _state: {"nonce": "verified", "code_verifier": "used"})
    monkeypatch.setattr(oidc, "_exchange_code", lambda *_args: {"sub": "real-issuer-sub", "role": "operator", "tenant_id": "untrusted"})
    inserted = []

    class Cursor:
        def execute(self, query, params=None):
            inserted.append((query, params))
            return self

    @contextmanager
    def connection():
        yield Cursor()

    monkeypatch.setattr(oidc.db, "connection", connection)
    response = Response()
    destination = oidc.finish_login("authorization-code", "one-time-state", None, response)
    cookie = response.headers["set-cookie"].lower()
    assert destination == "https://app.example.test/"
    assert "rs_session=" in cookie and "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert len(inserted) == 2 and inserted[-1][1][1] == "real-issuer-sub"
    assert inserted[-1][1][0] not in response.headers["set-cookie"]


def test_rate_limiter_is_bounded_and_enforces_route_client_window():
    limiter = BoundedWindowLimiter(max_entries=2, window_seconds=60)
    assert limiter.allow("client-1", "write", 2, now=100) == (True, 60)
    assert limiter.allow("client-1", "write", 2, now=101) == (True, 59)
    assert limiter.allow("client-1", "write", 2, now=102) == (False, 58)
    limiter.allow("client-2", "write", 2, now=102)
    limiter.allow("client-3", "write", 2, now=102)
    assert len(limiter.entries) <= 2
    assert limiter.allow("client-1", "write", 2, now=160) == (True, 60)


def test_mutating_routes_and_login_are_rate_limited_without_logging_request_secrets(monkeypatch, caplog):
    app = FastAPI()
    limiter = BoundedWindowLimiter(max_entries=4)
    monkeypatch.setattr(observability, "get_settings", lambda: SimpleNamespace(login_rate_per_minute=1, mutation_rate_per_minute=1))
    meter = ObservabilityMiddleware(app, limiter=limiter)
    app.add_middleware(ObservabilityMiddleware, limiter=limiter)

    @app.post("/api/grants/{grant_id}/authorize")
    def mutate(grant_id: str, request: Request):
        return {"ok": True}

    @app.get("/api/auth/login")
    def login():
        return {"ok": True}

    client = TestClient(app)
    caplog.set_level("INFO", logger="rewindsafe.http")
    first = client.post("/api/grants/grant_abc123/authorize?access_token=do-not-log", json={"password": "hidden"})
    second = client.post("/api/grants/grant_abc123/authorize", json={})
    login_first = client.get("/api/auth/login")
    login_second = client.get("/api/auth/login")
    assert first.status_code == 200 and first.headers.get("x-trace-id")
    assert second.status_code == 429 and second.headers.get("retry-after")
    assert login_first.status_code == 200
    assert login_second.status_code == 429
    assert "do-not-log" not in caplog.text and "hidden" not in caplog.text
    exposition = meter.prometheus()
    assert "/api/grants/{grant_id}/authorize" in exposition
    assert "grant_abc123" not in exposition and "do-not-log" not in exposition


def test_oidc_operator_cannot_invoke_demo_reset_or_privileged_control(monkeypatch):
    from rewindsafe.api import auth, routes_admin, routes_verification
    from rewindsafe.api.app import create_app
    from rewindsafe.contracts import Identity

    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(auth_mode="oidc"))
    identity = Identity(identity_id="real-operator", **{k: v for k, v in _mapping().items() if k != "identity_id"})
    app = create_app(run_startup=False)
    app.dependency_overrides[auth.current_identity] = lambda: identity
    mutations = []
    monkeypatch.setattr(routes_admin, "safe_reset", lambda *_: mutations.append("reset"))
    monkeypatch.setattr(routes_verification.verification_jobs, "start", lambda: mutations.append("suite"))
    client = TestClient(app)
    for endpoint in ("/api/admin/reset", "/api/admin/positive-control", "/api/verification/run"):
        response = client.post(endpoint)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "demo_only"
    assert mutations == []
