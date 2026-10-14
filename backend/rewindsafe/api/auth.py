"""Demo cookie sessions or OIDC-backed server sessions.

The cookie ``rs_session`` holds an itsdangerous-signed ``identity_id``. Roles and
tenants always come from the server-side identity table; anything a caller sends
(emails, roles, tenant ids) is ignored.
"""

from __future__ import annotations

from fastapi import Depends, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from rewindsafe.api.errors import forbidden, not_found, unauthenticated
from rewindsafe.api.settings_access import get_settings
from rewindsafe.contracts import Identity
from rewindsafe.runtime import identities

COOKIE_NAME = "rs_session"
SESSION_MAX_AGE_SECONDS = 12 * 3600
_SALT = "rewindsafe.session.v1"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt=_SALT)


def issue_token(identity_id: str) -> str:
    return _serializer().dumps(identity_id)


def read_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        value = _serializer().loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except BadSignature:  # includes SignatureExpired
        return None
    return value if isinstance(value, str) else None


def set_session_cookie(response: Response, identity_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        issue_token(identity_id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=bool(getattr(get_settings(), "cookie_secure", False)),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=bool(getattr(get_settings(), "cookie_secure", False)),
    )


def optional_identity(request: Request) -> Identity | None:
    if getattr(get_settings(), "auth_mode", "demo") == "oidc":
        from rewindsafe.api.oidc import identity_from_request

        return identity_from_request(request)
    identity_id = read_token(request.cookies.get(COOKIE_NAME))
    return identities.get_identity(identity_id) if identity_id else None


def current_identity(request: Request) -> Identity:
    identity = optional_identity(request)
    if identity is None:
        if getattr(get_settings(), "auth_mode", "demo") == "oidc":
            raise unauthenticated("Sign in through your organization identity provider.")
        raise unauthenticated()
    return identity


def identities_for(identity: Identity | None) -> list[Identity]:
    if getattr(get_settings(), "auth_mode", "demo") != "oidc":
        return list(identities.IDENTITIES.values())
    if identity is None:
        raise unauthenticated("Sign in through your organization identity provider.")
    from rewindsafe.api.oidc import identities_for_tenant

    return identities_for_tenant(identity.tenant_id)


def require_operator(identity: Identity = Depends(current_identity)) -> Identity:
    if identity.role != "operator":
        raise forbidden("This action needs an operator session.", "operator_required")
    return identity


def refuse_in_production() -> None:
    """Demo-only surfaces are not found at all in production, whoever is signed in."""
    if getattr(get_settings(), "environment", "development") == "production":
        raise not_found()


def require_demo_operator(identity: Identity = Depends(require_operator)) -> Identity:
    refuse_in_production()
    if getattr(get_settings(), "auth_mode", "demo") != "demo":
        raise forbidden("Demo resets and privileged demonstrations are disabled for organization sign-in.", "demo_only")
    return identity


def require_reviewer(identity: Identity = Depends(current_identity)) -> Identity:
    if identity.role != "reviewer":
        raise forbidden("Only a second reviewer (Orion) can decide approvals.", "reviewer_required")
    return identity
