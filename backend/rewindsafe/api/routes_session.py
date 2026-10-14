"""Demo identities and cookie sessions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from rewindsafe.api import auth
from rewindsafe.api.errors import not_found
from rewindsafe.contracts import Identity
from rewindsafe.runtime import identities

router = APIRouter(prefix="/api", tags=["session"])


class SessionBody(BaseModel):
    identity_id: str  # anything else the caller sends (email, role, tenant) is ignored


@router.get("/identities", response_model=list[Identity])
def list_identities(request: Request) -> list[Identity]:
    return auth.identities_for(auth.optional_identity(request))


@router.post("/session", response_model=Identity)
def create_session(body: SessionBody, response: Response) -> Identity:
    if getattr(auth.get_settings(), "auth_mode", "demo") == "oidc":
        from rewindsafe.api.errors import forbidden

        raise forbidden("Local identity selection is disabled. Use your organization sign-in.", "oidc_login_required")
    identity = identities.get_identity(body.identity_id)
    if identity is None:
        raise not_found("Unknown demo identity.")
    auth.set_session_cookie(response, identity.identity_id)
    return identity


@router.get("/session", response_model=Identity)
def read_session(identity: Identity = Depends(auth.current_identity)) -> Identity:
    return identity


@router.post("/session/logout")
def logout(request: Request, response: Response) -> dict:
    if getattr(auth.get_settings(), "auth_mode", "demo") == "oidc":
        from rewindsafe.api.oidc import revoke_request_session

        revoke_request_session(request)
    auth.clear_session_cookie(response)
    return {"ok": True}
