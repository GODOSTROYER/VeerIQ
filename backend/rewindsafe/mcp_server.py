"""MCP server over the same dispatcher.

    python -m rewindsafe.mcp_server --grant <grant_id>                 # stdio
    python -m rewindsafe.mcp_server --grant <grant_id> --http --port 8765
    python -m rewindsafe.mcp_server --run <run_id>                     # alias: resolves the run's grant

HTTP needs REWINDSAFE_MCP_TOKEN: it is required for any non-loopback --host, and once set every HTTP
request must send ``Authorization: Bearer <token>``. stdio needs no token.

Bring your own agent: the server takes an authorized (ACTIVE) grant that no run is using,
creates its OWN run (planner "mcp-client"), binds a signed ArmorIQ plan from the grant in
this process, and serves the six workflow tools (``adapter.tool_specs()``). There is no other
path to effects: every call goes through ``dispatch(rc, tool, args, source="mcp")``, so ArmorIQ
plan binding, the grant scope, domain invariants, approvals and the PostgreSQL role all apply
exactly as they do for the in-process agent. On exit the plan is completed, the run is closed
out and the grant ends (one grant = one run). Nothing here ever returns credentials or tokens.

Note: mcp>=2 renamed ``FastMCP`` to ``MCPServer``; both spellings are supported.
"""

from __future__ import annotations

import argparse
import atexit
import hmac
import json
import logging
import os
import signal
import sys
import threading
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError

    _MCP_V2 = True
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]
    from mcp.server.fastmcp.exceptions import ToolError  # type: ignore[no-redef]

    _MCP_V2 = False

from rewindsafe.agent.planners import load_settings, tool_result_payload
from rewindsafe.contracts import DispatchOutcome, GrantStatus, RunStatus, ToolSpec

log = logging.getLogger("rewindsafe.mcp")

TOOL_NAMES = (
    "inspect_snapshot",
    "compare_current",
    "prepare_repair_manifest",
    "apply_repair_manifest",
    "get_recovery_receipt",
    "restore_access_grant",
)


class RunBridge:
    """Binds one authorized grant to the dispatcher for an MCP client (own run, own signed plan)."""

    def __init__(
        self,
        grant_id: str | None = None,
        *,
        run_id: str | None = None,
        gateway: Any = None,
        return_outcome: bool = False,
    ) -> None:
        from rewindsafe.agent import loop
        from rewindsafe.agent.planners import load_settings
        from rewindsafe.runtime import grants
        from rewindsafe.runtime.armoriq_gateway import get_gateway
        from rewindsafe.runtime.dispatch import RunContext
        from rewindsafe.runtime.identities import get_identity

        if grant_id is None:
            if run_id is None:
                raise ValueError("Provide a grant id (or a run id whose grant should be used).")
            grant_id = loop.get_run(run_id).grant_id  # KeyError when the run does not exist
        grant = grants.load(grant_id)
        if grant.status is not GrantStatus.ACTIVE:
            raise ToolError(
                f"Refused: grant {grant_id} is {grant.status.value}, not active. "
                "Authorize a grant (one grant = one run) before using the MCP server."
            )
        busy = loop.active_run_for_grant(grant_id)
        if busy:
            raise ToolError(f"Refused: run {busy} is already using grant {grant_id}.")
        blocked = grants.lifecycle_check(grant, grants.current_generation())
        if blocked is not None:
            raise ToolError(f"Refused: {blocked.reason}")
        identity = get_identity(grant.principal)
        if identity is None:
            raise ValueError(f"Grant principal {grant.principal!r} is not a known identity.")
        adapter = loop._resolve_adapter(grant.workflow)
        scenario = next(s for s in adapter.scenarios() if s.scenario_id == grant.scenario_id)
        self.gateway = gateway if gateway is not None else get_gateway()
        self.grant_id = grant.grant_id
        # VeerIQ's own MCP agent asks for the full dispatcher outcome so its planners reason over the
        # real decision (status, deciding layer, manifest digest). Other clients get the plain result.
        self.return_outcome = return_outcome
        self.adapter = adapter
        self.history: list[tuple[Any, DispatchOutcome]] = []
        self._closed = False
        self._lock = threading.Lock()  # one effect at a time per run
        self.run_id = loop.create_run_row(
            grant,
            scenario,
            planner_name="mcp-client",
            planner_kind="llm",
            planner_label="External agent over MCP",
            enforcement_mode=self.gateway.mode,
            created_by=identity.identity_id,
            extra_metadata={"via": "mcp"},
        )
        loop._set_status(self.run_id, RunStatus.PLANNING)
        email = getattr(load_settings(), "armoriq_user_email", "") or identity.email
        binding, error = loop.bind_plan_for_run(
            self.run_id, grant, adapter, self.gateway, email, llm="mcp-client"
        )
        if binding is None:
            self._finish(
                RunStatus.FAILED,
                f"The signed ArmorIQ plan could not be created ({error}); no MCP call was served.",
            )
            raise ToolError(f"ArmorIQ plan binding failed: {error}")
        self.rc = RunContext(
            run_id=self.run_id,
            grant=grant,
            identity=identity,
            adapter=adapter,
            gateway=self.gateway,
            scenario=scenario,
            cancel=threading.Event(),
        )
        loop._set_status(self.run_id, RunStatus.EXECUTING)

    def assert_active(self) -> None:
        from rewindsafe.runtime import grants

        grant = grants.load(self.grant_id)
        # The grant allows one commit; once this run has spent it, the run may still read its own
        # receipt. The dispatcher's lifecycle gate decides what an exhausted grant still permits.
        spent_here = grant.status is GrantStatus.EXHAUSTED and any(
            o.receipt is not None for _, o in self.history
        )
        if grant.status is not GrantStatus.ACTIVE and not spent_here:
            raise ToolError(
                f"Refused: the grant for run {self.run_id} is {grant.status.value}, not active. "
                "Authorize a grant before using the MCP server."
            )
        self.rc.grant = grant

    def specs(self) -> dict[str, ToolSpec]:
        return {s.name: s for s in self.adapter.tool_specs()}

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        from rewindsafe.agent.state import ToolCall
        from rewindsafe.runtime.dispatch import dispatch

        with self._lock:
            if self._closed:
                raise ToolError(f"Refused: the MCP session for run {self.run_id} has ended.")
            self.assert_active()
            outcome: DispatchOutcome = dispatch(
                self.rc, tool, args, rationale="Request from an MCP client", source="mcp"
            )
            self.history.append((ToolCall(tool, dict(args), source="mcp"), outcome))
        content, is_error = tool_result_payload(outcome)
        if self.return_outcome:
            return {
                "run_id": self.run_id,
                "is_error": is_error,
                "result": json.loads(content),
                "outcome": outcome.model_dump(mode="json"),
            }
        if is_error:
            raise ToolError(content)  # surfaces as an MCP error result carrying the dispatcher's guidance
        return json.loads(content)

    def _finish(self, status: RunStatus, summary: str) -> None:
        from rewindsafe.agent import loop

        try:
            loop._finish_run(self.run_id, status, summary, {"via": "mcp"}, handle=None)
        except Exception:
            log.exception("could not close MCP run %s", self.run_id)
        loop._close_gateway_run(self.gateway, self.run_id)  # live: completes the ArmorIQ plan

    def close(self) -> None:
        """End the session once (idempotent): close the plan, record the outcome, end the grant."""
        from rewindsafe.agent.state import build_outcome_summary, terminal_status

        with self._lock:
            if self._closed:
                return
            self._closed = True
        grant = self.rc.grant
        if not self.history:
            self._finish(RunStatus.CANCELLED, "The MCP session ended without any tool call.")
            return
        orders = list(grant.resources.get("order", [])) + list(grant.reviewable.get("order", []))
        status = terminal_status(self.history, orders, cancelled=False, failure=None)
        summary = build_outcome_summary(
            self.history, grant, status, note="The external agent's MCP session ended."
        )
        self._finish(status, summary)


def _drop_none(**kw: Any) -> dict[str, Any]:
    return {k: v for k, v in kw.items() if v is not None}


def build_server(
    grant_id: str | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    run_id: str | None = None,
    gateway: Any = None,
    return_outcome: bool | None = None,
) -> Any:
    if return_outcome is None:
        return_outcome = os.environ.get("REWINDSAFE_MCP_RETURN_OUTCOME", "").strip() == "1"
    bridge = RunBridge(grant_id, run_id=run_id, gateway=gateway)
    bridge.return_outcome = return_outcome
    specs = bridge.specs()

    def desc(name: str) -> str:
        s = specs.get(name)
        return s.description if s else name

    kwargs: dict[str, Any] = {
        "instructions": (
            "RewindSafe recovery tools for one authorized task grant. Every call is checked by ArmorIQ plan "
            "binding, the grant scope, domain invariants and PostgreSQL before any effect."
        )
    }
    if not _MCP_V2:
        kwargs.update(host=host, port=port)
    server = _Server("rewindsafe-recovery", **kwargs)
    server.rewindsafe_bridge = bridge  # type: ignore[attr-defined]  # so callers can close the session

    def inspect_snapshot(
        snapshot_id: str, tenant_id: str, order_ids: list[str] | None = None
    ) -> dict[str, Any]:
        return bridge.call(
            "inspect_snapshot", _drop_none(snapshot_id=snapshot_id, tenant_id=tenant_id, order_ids=order_ids)
        )

    def compare_current(tenant_id: str, order_ids: list[str]) -> dict[str, Any]:
        return bridge.call("compare_current", {"tenant_id": tenant_id, "order_ids": order_ids})

    def prepare_repair_manifest(
        tenant_id: str, snapshot_id: str, repairs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return bridge.call(
            "prepare_repair_manifest",
            {"tenant_id": tenant_id, "snapshot_id": snapshot_id, "repairs": repairs},
        )

    def apply_repair_manifest(manifest_id: str, manifest_digest: str, idempotency_key: str) -> dict[str, Any]:
        return bridge.call(
            "apply_repair_manifest",
            {
                "manifest_id": manifest_id,
                "manifest_digest": manifest_digest,
                "idempotency_key": idempotency_key,
            },
        )

    def get_recovery_receipt(
        operation_id: str | None = None, manifest_id: str | None = None
    ) -> dict[str, Any]:
        return bridge.call(
            "get_recovery_receipt", _drop_none(operation_id=operation_id, manifest_id=manifest_id)
        )

    def restore_access_grant(tenant_id: str, grant_id: str, reason: str) -> dict[str, Any]:
        return bridge.call(
            "restore_access_grant", {"tenant_id": tenant_id, "grant_id": grant_id, "reason": reason}
        )

    for fn in (
        inspect_snapshot,
        compare_current,
        prepare_repair_manifest,
        apply_repair_manifest,
        get_recovery_receipt,
        restore_access_grant,
    ):
        server.add_tool(fn, name=fn.__name__, description=desc(fn.__name__))
    return server


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def bearer_token_valid(header: str | None, expected: str) -> bool:
    """True only for ``Authorization: Bearer <expected>`` (scheme case-insensitive, constant-time compare)."""
    if not expected or not header:
        return False
    scheme, _, supplied = header.strip().partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(supplied.strip().encode(), expected.encode())


def _authorization(scope: Scope) -> str | None:
    values = [value for name, value in scope.get("headers", []) if name == b"authorization"]
    return values[0].decode("latin-1") if len(values) == 1 else None


class BearerTokenMiddleware:
    """Pure ASGI guard: each HTTP request must carry the bearer token before the MCP app sees it."""

    def __init__(self, app: Any, token: str) -> None:
        if not token:
            raise ValueError("BearerTokenMiddleware requires a non-empty token")
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        is_request = scope["type"] in ("http", "websocket")
        if not is_request or bearer_token_valid(_authorization(scope), self.token):
            await self.app(scope, receive, send)  # lifespan events pass through untouched
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            response = JSONResponse(
                {"error": {"code": "unauthenticated", "message": "Missing or invalid MCP bearer token."}},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)


def _serve_http(server: Any, host: str, port: int, token: str) -> None:
    """Serve the app FastMCP's run('streamable-http') serves, behind the bearer guard when a token is set."""
    import uvicorn

    app: Any = server.streamable_http_app(host=host) if _MCP_V2 else server.streamable_http_app()
    if token:
        app = BearerTokenMiddleware(app, token)
    uvicorn.run(app, host=host, port=port, log_level="info")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rewindsafe.mcp_server", description=__doc__.split("\n\n")[0])
    ap.add_argument("--grant", help="grant_id of an authorized (ACTIVE) grant no run is using")
    ap.add_argument("--run", help="alias: use the grant of this existing run")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    if not args.grant and not args.run:
        ap.error("one of --grant or --run is required")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)  # stdout belongs to the stdio transport
    token = (getattr(load_settings(), "mcp_token", "") or "").strip()
    if args.http and args.host.strip().lower() not in LOOPBACK_HOSTS and not token:
        print(
            f"rewindsafe-mcp: refusing HTTP on non-loopback host {args.host!r} without REWINDSAFE_MCP_TOKEN; "
            "set the token or bind 127.0.0.1",
            file=sys.stderr,
        )
        return 2  # refused before any run is created or any ArmorIQ plan is bound
    try:
        server = build_server(args.grant, host=args.host, port=args.port, run_id=args.run)
    except (KeyError, ValueError, ToolError) as exc:
        print(f"rewindsafe-mcp: {exc}", file=sys.stderr)
        return 2
    bridge = server.rewindsafe_bridge
    atexit.register(bridge.close)

    def _stop(signum: int, _frame: Any) -> None:
        bridge.close()
        raise SystemExit(0)

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _stop)
            except (ValueError, OSError):  # not the main thread / unsupported here
                pass
    try:
        if args.http:
            _serve_http(server, args.host, args.port, token)
        else:
            server.run()
    finally:
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
