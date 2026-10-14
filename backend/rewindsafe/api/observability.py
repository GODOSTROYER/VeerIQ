"""Bounded request logging, rate limits, health checks, and aggregate Prometheus metrics."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from contextvars import ContextVar
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from rewindsafe.api.settings_access import get_settings

log = logging.getLogger("rewindsafe.http")
trace_id_var: ContextVar[str] = ContextVar("veeriq_trace_id", default="")
_run_id_pattern = re.compile(r"^/api/runs/([A-Za-z0-9_-]{1,80})(?:/|$)")
_metrics_lock = threading.Lock()
_request_counts: dict[tuple[str, str, int], int] = {}
_duration_totals: dict[tuple[str, str], float] = {}


class BoundedWindowLimiter:
    """Small per-process fixed-window limiter with an explicit memory bound."""

    def __init__(self, max_entries: int = 10_000, window_seconds: int = 60) -> None:
        self.max_entries = max_entries
        self.window_seconds = window_seconds
        self.entries: OrderedDict[tuple[str, str], tuple[int, int]] = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, client: str, bucket: str, limit: int, now: int | None = None) -> tuple[bool, int]:
        current = int(time.time()) if now is None else now
        key = (client, bucket)
        with self.lock:
            for old_key, (started, _) in list(self.entries.items()):
                if current - started >= self.window_seconds:
                    del self.entries[old_key]
            started, count = self.entries.get(key, (current, 0))
            if current - started >= self.window_seconds:
                started, count = current, 0
            allowed = count < limit
            if allowed:
                count += 1
            self.entries[key] = (started, count)
            self.entries.move_to_end(key)
            while len(self.entries) > self.max_entries:
                self.entries.popitem(last=False)
            retry = max(1, self.window_seconds - (current - started))
            return allowed, retry


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, limiter: BoundedWindowLimiter | None = None) -> None:
        super().__init__(app)
        self.limiter = limiter or BoundedWindowLimiter()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        trace_id = uuid.uuid4().hex
        trace_token = trace_id_var.set(trace_id)
        started = time.perf_counter()
        route = request.scope.get("route")
        route_label = getattr(route, "path", None) or _safe_route(request.url.path)
        bucket = _mutation_bucket(request.method, request.url.path)
        response: Response
        rate_limited = False
        try:
            if bucket:
                address = request.client.host if request.client else "unknown"
                settings = get_settings()
                limit = settings.login_rate_per_minute if bucket == "login" else settings.mutation_rate_per_minute
                allowed, retry = self.limiter.allow(address, bucket, int(limit))
                if not allowed:
                    rate_limited = True
                    response = JSONResponse(
                        {"error": {"code": "rate_limited", "message": "Too many requests. Try again shortly."}},
                        status_code=429,
                        headers={"Retry-After": str(retry)},
                    )
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        except Exception:
            self._record(request.method, route_label, 500, time.perf_counter() - started)
            trace_id_var.reset(trace_token)
            raise
        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        route_label = getattr(route, "path", None) or (
            "rate_limited" if rate_limited else request.url.path if bucket == "login" else "unmatched"
        )
        route_label = _safe_route(route_label)
        response.headers["X-Trace-ID"] = trace_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.url.path.startswith("/api/auth/") or request.url.path.startswith("/api/session"):
            response.headers["Cache-Control"] = "no-store"
        self._record(request.method, route_label, response.status_code, elapsed)
        match = _run_id_pattern.match(request.url.path)
        record = {
            "event": "http_request",
            "trace_id": trace_id,
            "run_id": match.group(1) if match else None,
            "method": request.method,
            "route": route_label,
            "status": response.status_code,
            "duration_ms": round(elapsed * 1000, 2),
        }
        log.info(json.dumps(record, separators=(",", ":"), ensure_ascii=False))
        trace_id_var.reset(trace_token)
        return response

    def _record(self, method: str, route: str, status: int, elapsed: float) -> None:
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            method = "OTHER"
        key = (method, route, status)
        duration_key = (method, route)
        with _metrics_lock:
            _request_counts[key] = _request_counts.get(key, 0) + 1
            _duration_totals[duration_key] = _duration_totals.get(duration_key, 0.0) + elapsed

    def prometheus(self) -> str:
        with _metrics_lock:
            counts = sorted(_request_counts.items())
            durations = sorted(_duration_totals.items())
        lines = [
            "# HELP veeriq_http_requests_total HTTP requests completed by route template and status.",
            "# TYPE veeriq_http_requests_total counter",
        ]
        for (method, route, status), count in counts:
            lines.append(f'veeriq_http_requests_total{{method="{method}",route="{_label(route)}",status="{status}"}} {count}')
        lines.extend([
            "# HELP veeriq_http_request_duration_seconds Request duration summary by route template.",
            "# TYPE veeriq_http_request_duration_seconds summary",
        ])
        for (method, route), total in durations:
            labels = f'method="{method}",route="{_label(route)}"'
            count = sum(n for (m, r, _), n in counts if (m, r) == (method, route))
            lines.append(f'veeriq_http_request_duration_seconds_sum{{{labels}}} {total:.6f}')
            lines.append(f'veeriq_http_request_duration_seconds_count{{{labels}}} {count}')
        return "\n".join(lines) + "\n"


def _safe_route(path: str) -> str:
    path = re.sub(r"/[A-Za-z0-9_-]{12,}(?=/|$)", "/{id}", path)
    return path[:160]


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _mutation_bucket(method: str, path: str) -> str | None:
    if path in {"/api/auth/login", "/api/auth/callback"}:
        return "login"
    if method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/"):
        return "write"
    return None


router = APIRouter(tags=["observability"])
_middleware: ObservabilityMiddleware | None = None


def install(app: Any) -> ObservabilityMiddleware:
    """Install once during app creation and return the middleware for tests/use."""
    global _middleware
    middleware = ObservabilityMiddleware(app)
    app.add_middleware(ObservabilityMiddleware, limiter=middleware.limiter)
    _middleware = middleware
    return middleware


@router.get("/api/health/live")
def live() -> dict[str, bool]:
    return {"ok": True}


@router.get("/api/health/ready")
def ready() -> JSONResponse:
    try:
        from rewindsafe.runtime import db

        with db.connection() as conn:
            conn.execute("SELECT 1")
        return JSONResponse({"ok": True, "database": "ready"})
    except Exception:  # noqa: BLE001 - a health endpoint must not leak database failure details
        return JSONResponse({"ok": False, "database": "unavailable"}, status_code=503)


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> PlainTextResponse:
    """Aggregate process metrics only; no identity, tenant, run, or request values."""
    if _middleware is None:
        return PlainTextResponse("# no requests recorded\n", media_type="text/plain; version=0.0.4")
    return PlainTextResponse(_middleware.prometheus(), media_type="text/plain; version=0.0.4")
