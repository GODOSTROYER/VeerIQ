"""FastAPI application: ``uvicorn rewindsafe.api.app:app``.

Startup (lifespan): migrate + seed the database, register the RewindSafe
workflow adapter, resolve the ArmorIQ gateway (fails loudly when
``REWINDSAFE_ENFORCEMENT=live`` has no key). In a production build the app also
serves ``frontend/dist`` with a single-page-app fallback.
"""

from __future__ import annotations

import importlib
import logging
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from rewindsafe.api import (
    routes_admin,
    routes_app,
    routes_approvals,
    routes_imports,
    routes_oidc,
    routes_reliability,
    routes_runs,
    routes_session,
    routes_system,
    routes_verification,
)
from rewindsafe.api import oidc, observability
from rewindsafe.api.errors import install_error_handlers, not_found
from rewindsafe.api.settings_access import get_settings
from rewindsafe.runtime import armoriq_gateway, db

log = logging.getLogger("rewindsafe.api")

CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"

# Windows' registry can map .js to text/plain, which browsers refuse as a module script.
for _ext, _type in ((".js", "text/javascript"), (".mjs", "text/javascript"), (".css", "text/css"),
                    (".svg", "image/svg+xml"), (".woff2", "font/woff2")):
    mimetypes.add_type(_type, _ext)


def startup() -> None:
    """Prepare the database and enforcement gateway; raise on any misconfiguration."""
    get_settings().validate_startup()  # live enforcement without a key raises, never degrades
    oidc.validate_startup()
    db.ensure_database_ready()
    importlib.import_module("rewindsafe.workflows.rewindsafe")  # registers the adapter
    importlib.import_module("rewindsafe.workflows.import_recovery").register()  # explicit adapter registration
    gateway = armoriq_gateway.get_gateway()
    log.info("ArmorIQ enforcement mode: %s (simulated=%s)", gateway.mode, gateway.describe().get("simulated"))


def create_app(*, run_startup: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if run_startup:
            startup()
        yield

    app = FastAPI(
        title="RewindSafe API",
        description="Restore yesterday's data. Keep today's decisions.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    observability.install(app)

    for module in (
        observability,
        routes_session,
        routes_system,
        routes_app,
        routes_runs,
        routes_approvals,
        routes_admin,
        routes_imports,
        routes_oidc,
        routes_reliability,
        routes_verification,
    ):
        app.include_router(module.router)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def unknown_api_route(rest: str) -> None:
        raise not_found("No such API route.")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str, request: Request) -> FileResponse:
        """Serve the built SPA (when ``frontend/dist`` exists) with index.html fallback."""
        index = DIST_DIR / "index.html"
        if not index.is_file():
            raise not_found("Frontend is not built. Run `python tasks.py build`, or use the dev server on :5173.")
        candidate = (DIST_DIR / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(DIST_DIR.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)

    return app


app = create_app()
