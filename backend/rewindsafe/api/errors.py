"""Uniform error format: ``{"error": {"code": str, "message": str}}``."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("rewindsafe.api")

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
}


class ApiError(Exception):
    """Raise from any route or dependency; rendered in the standard error format."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def bad_request(message: str, code: str = "bad_request") -> ApiError:
    return ApiError(400, code, message)


def unauthenticated(message: str = "Sign in as a demo identity first.") -> ApiError:
    return ApiError(401, "unauthenticated", message)


def forbidden(message: str, code: str = "forbidden") -> ApiError:
    return ApiError(403, code, message)


def not_found(message: str = "Not found.") -> ApiError:
    return ApiError(404, "not_found", message)


def conflict(message: str, code: str = "conflict") -> ApiError:
    return ApiError(409, code, message)


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _render(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_body(code, message))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _render(exc.status_code, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "error")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ")
        return _render(exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for err in exc.errors()[:3]:
            loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
            parts.append(f"{loc}: {err.get('msg', 'invalid')}" if loc else str(err.get("msg", "invalid")))
        return _render(400, "invalid_request", "; ".join(parts) or "Invalid request.")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Never leak internals (connection strings, SQL, keys) to the browser.
        log.exception("Unhandled error", exc_info=exc)
        return _render(500, "internal_error", "Unexpected server error. See the server log.")
