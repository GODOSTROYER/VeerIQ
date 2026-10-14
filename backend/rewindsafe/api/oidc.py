"""OpenID Connect authorization-code flow and opaque server-side sessions."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from fastapi import Request, Response
from jwt import PyJWK

from rewindsafe.api.errors import ApiError, bad_request, forbidden
from rewindsafe.api.settings_access import get_settings
from rewindsafe.contracts import Identity
from rewindsafe.runtime import db

SESSION_COOKIE = "rs_session"
SESSION_SECONDS = 12 * 60 * 60
STATE_SECONDS = 10 * 60
ALLOWED_ALGORITHMS = ["RS256", "ES256", "EdDSA"]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@lru_cache(maxsize=4)
def discovery(issuer: str) -> dict[str, Any]:
    try:
        response = httpx.get(issuer.rstrip("/") + "/.well-known/openid-configuration", timeout=8.0)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ApiError(503, "oidc_unavailable", "The configured identity provider could not be reached.") from exc
    if not isinstance(data, dict) or data.get("issuer") != issuer or not data.get("authorization_endpoint") \
            or not data.get("token_endpoint") or not data.get("jwks_uri"):
        raise ApiError(503, "oidc_configuration_invalid", "The identity provider discovery document is incomplete or has a mismatched issuer.")
    if any(urlsplit(str(data[key])).scheme != "https" for key in ("authorization_endpoint", "token_endpoint", "jwks_uri")):
        raise ApiError(503, "oidc_configuration_invalid", "The identity provider endpoints must all use HTTPS.")
    return data


def validate_startup() -> None:
    """Validate OIDC configuration and issuer discovery before serving production traffic."""
    settings = get_settings()
    if settings.auth_mode != "oidc":
        return
    settings.validate_startup()
    discovery(settings.oidc_issuer)


def auth_config() -> dict[str, str]:
    mode = getattr(get_settings(), "auth_mode", "demo")
    return {"mode": mode, "login_url": "/api/auth/login"}


def _save_login_state(state: str, nonce: str, verifier: str) -> None:
    with db.connection() as conn:
        conn.execute("DELETE FROM runtime.oidc_login_states WHERE expires_at <= now()")
        conn.execute(
            "INSERT INTO runtime.oidc_login_states (state_hash, nonce, code_verifier, expires_at) "
            "VALUES (%s, %s, %s, now() + (%s * interval '1 second'))",
            (_hash(state), nonce, verifier, STATE_SECONDS),
        )


def begin_login() -> str:
    settings = get_settings()
    if settings.auth_mode != "oidc":
        raise ApiError(404, "oidc_disabled", "OIDC login is not enabled in demo authentication mode.")
    metadata = discovery(settings.oidc_issuer)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    _save_login_state(state, nonce, verifier)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    query = urlencode({
        "client_id": settings.oidc_client_id,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": settings.oidc_redirect_uri,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return str(metadata["authorization_endpoint"]) + ("&" if "?" in metadata["authorization_endpoint"] else "?") + query


def _consume_login_state(state: str) -> dict[str, Any] | None:
    with db.connection() as conn:
        conn.execute("DELETE FROM runtime.oidc_login_states WHERE expires_at <= now()")
        return conn.execute(
            "DELETE FROM runtime.oidc_login_states WHERE state_hash = %s AND expires_at > now() "
            "RETURNING nonce, code_verifier",
            (_hash(state),),
        ).fetchone()


def _key_for_token(token: str, jwks_uri: str) -> tuple[Any, str]:
    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        kid = header.get("kid")
        if algorithm not in ALLOWED_ALGORITHMS or not isinstance(kid, str):
            raise ValueError("unsupported token header")
        response = httpx.get(jwks_uri, timeout=8.0)
        response.raise_for_status()
        keys = response.json().get("keys", [])
        match = next((
            item for item in keys
            if item.get("kid") == kid
            and item.get("use", "sig") == "sig"
            and item.get("alg", algorithm) == algorithm
            and (not item.get("key_ops") or "verify" in item["key_ops"])
        ), None)
        if match is None:
            raise ValueError("matching signing key not found")
        return PyJWK.from_dict(match, algorithm=algorithm).key, algorithm
    except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError) as exc:
        raise ApiError(401, "oidc_token_invalid", "The identity provider returned an unverifiable token.") from exc


def _exchange_code(code: str, verifier: str, nonce: str) -> dict[str, Any]:
    settings = get_settings()
    metadata = discovery(settings.oidc_issuer)
    try:
        response = httpx.post(
            metadata["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oidc_redirect_uri,
                "client_id": settings.oidc_client_id,
                "code_verifier": verifier,
            },
            auth=(settings.oidc_client_id, settings.oidc_client_secret),
            timeout=10.0,
        )
        response.raise_for_status()
        body = response.json()
        token = body.get("id_token") if isinstance(body, dict) else None
        if not isinstance(token, str):
            raise TypeError("missing ID token")
        key, algorithm = _key_for_token(token, str(metadata["jwks_uri"]))
        claims = jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            issuer=settings.oidc_issuer,
            audience=settings.oidc_client_id,
            options={"require": ["iss", "aud", "sub", "exp", "iat", "nonce"]},
            leeway=30,
        )
        audiences = claims.get("aud")
        if (isinstance(audiences, list) and len(audiences) > 1 and claims.get("azp") != settings.oidc_client_id) \
                or (claims.get("azp") is not None and claims.get("azp") != settings.oidc_client_id):
            raise ValueError("authorized party mismatch")
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise ValueError("nonce mismatch")
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise ValueError("missing subject")
        return claims
    except ApiError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError) as exc:
        raise ApiError(401, "oidc_token_invalid", "The identity provider response failed token validation.") from exc


def _identity_for_subject(subject: str) -> Identity:
    mapping = get_settings().oidc_subject_mappings().get(subject)
    if mapping is None:
        raise forbidden("Your identity provider account is not mapped to a VeerIQ tenant and role.", "oidc_subject_unmapped")
    return Identity.model_validate(mapping)


def finish_login(code: str | None, state: str | None, error: str | None, response: Response) -> str:
    if error:
        raise bad_request("The identity provider did not complete sign-in.", "oidc_login_cancelled")
    if not code or not state:
        raise bad_request("The identity provider callback is missing its authorization code or state.", "oidc_callback_invalid")
    login_state = _consume_login_state(state)
    if login_state is None:
        raise bad_request("The sign-in state is expired or has already been used. Start sign-in again.", "oidc_state_invalid")
    claims = _exchange_code(code, login_state["code_verifier"], login_state["nonce"])
    _identity_for_subject(claims["sub"])
    session_token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(seconds=SESSION_SECONDS)
    with db.connection() as conn:
        conn.execute("DELETE FROM runtime.auth_sessions WHERE expires_at <= now()")
        conn.execute(
            "INSERT INTO runtime.auth_sessions (session_hash, subject, expires_at) VALUES (%s, %s, %s)",
            (_hash(session_token), claims["sub"], expires),
        )
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return get_settings().oidc_app_origin.rstrip("/") + "/"


def identity_from_request(request: Request) -> Identity | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with db.connection() as conn:
        row = conn.execute(
            "SELECT subject FROM runtime.auth_sessions WHERE session_hash = %s AND expires_at > now()",
            (_hash(token),),
        ).fetchone()
    if not row:
        return None
    try:
        return _identity_for_subject(row["subject"])
    except ApiError:
        return None


def revoke_request_session(request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return
    with db.connection() as conn:
        conn.execute("DELETE FROM runtime.auth_sessions WHERE session_hash = %s", (_hash(token),))


def identities_for_tenant(tenant_id: str) -> list[Identity]:
    mappings = get_settings().oidc_subject_mappings()
    return [Identity.model_validate(entry) for entry in mappings.values() if entry["tenant_id"] == tenant_id]
