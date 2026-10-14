"""Public OIDC login contract and authorization-code callback."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response
from fastapi.responses import RedirectResponse

from rewindsafe.api import oidc

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.get("/config")
def auth_config() -> dict[str, str]:
    """Safe frontend bootstrap settings; never expose issuer secrets or mappings."""
    return oidc.auth_config()


@router.get("/login", include_in_schema=False)
def login() -> RedirectResponse:
    return RedirectResponse(oidc.begin_login(), status_code=302)


@router.get("/callback", include_in_schema=False)
def callback(
    response: Response,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    destination = oidc.finish_login(code, state, error, response)
    redirect = RedirectResponse(destination, status_code=303)
    # RedirectResponse is a distinct response object; carry the opaque session cookie forward.
    cookie = response.headers.get("set-cookie")
    if cookie:
        redirect.headers.append("set-cookie", cookie)
    return redirect
