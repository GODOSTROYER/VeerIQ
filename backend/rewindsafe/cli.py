"""RewindSafe command line: ``uv run python -m rewindsafe.cli <command>``.

Commands: migrate, reset, demo, verify, evidence, status. Everything runs
in-process against the same runtime the HTTP API uses; nothing here has a
privileged path around the dispatcher.

Exit codes: 0 ok; 1 a protected check was VIOLATED / verification failed;
2 blocked (e.g. verification could not run without ArmorIQ credentials);
3 the demo run failed or timed out; 130 interrupted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rewindsafe.contracts import (
    TERMINAL_RUN_STATUSES,
    Decision,
    Identity,
    InvariantStatus,
    RunEvent,
    RunStatus,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO_ROOT / "evidence"

EXIT_OK, EXIT_VIOLATED, EXIT_BLOCKED, EXIT_RUN_FAILED, EXIT_INTERRUPTED = 0, 1, 2, 3, 130

# ─── terminal output ───────────────────────────────────────────────────────

_COLOR = False


def _enable_windows_ansi() -> bool:
    """Turn on ANSI escape processing for the Windows console; False if unsupported."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (AttributeError, OSError):
        return False


def _init_terminal() -> None:
    global _COLOR
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
        _COLOR = _enable_windows_ansi() if os.name == "nt" else True


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def bold(t: str) -> str:
    return paint(t, "1")


def dim(t: str) -> str:
    return paint(t, "2")


LAYER_COLORS = {  # mirrors the UI palette
    "armoriq": "38;5;141",
    "grant": "38;5;75",
    "domain": "38;5;215",
    "approval": "38;5;211",
    "postgres": "38;5;43",
    "runtime": "38;5;103",
}
OUTCOME_COLORS = {
    "allow": "38;5;78", "block": "38;5;204", "hold": "38;5;214",
    "unavailable": "38;5;208", "error": "38;5;196", "skipped": "2",
}
ACTOR_COLORS = {
    "agent": "38;5;252", "armoriq": LAYER_COLORS["armoriq"], "rewindsafe": LAYER_COLORS["grant"],
    "postgres": LAYER_COLORS["postgres"], "operator": "38;5;215", "reviewer": "38;5;78",
    "system": "2", "harness": "38;5;179",
}


def render_event(event: RunEvent) -> str:
    ts = event.ts.astimezone().strftime("%H:%M:%S")
    head = dim(ts) + "  "
    if event.type == "decision" and event.decision is not None:
        d: Decision = event.decision
        layer = paint(f"{d.layer.value.upper():<8}", LAYER_COLORS.get(d.layer.value, "0"))
        outcome = paint(f"{d.outcome.value.upper():<11}", OUTCOME_COLORS.get(d.outcome.value, "0") + ";1")
        flags = ("  SIMULATED" if d.simulated else "") + ("  (shadow)" if d.shadow else "")
        line = f"{head}{layer} {outcome} {event.title}{paint(flags, '2')}"
    else:
        actor = ACTOR_COLORS.get(event.actor.value, "0")
        tag = paint(f"{event.actor.value:<10}", actor)
        title = bold(event.title) if event.type in {"run.finished", "execution.committed"} else event.title
        line = f"{head}{tag} {title}"
    if event.detail:
        line += "\n" + "\n".join(dim("          " + part) for part in event.detail.splitlines())
    return line


def status_chip(status: InvariantStatus) -> str:
    colors = {"preserved": "38;5;78", "repaired": "38;5;78", "pending": "38;5;214", "violated": "38;5;196;1"}
    return paint(f"{status.value.upper():<9}", colors.get(status.value, "0"))


# ─── bootstrap ─────────────────────────────────────────────────────────────


def bootstrap() -> None:
    """Migrate + seed the database and register the workflow adapter."""
    import importlib

    from rewindsafe.runtime import db

    db.ensure_database_ready()
    importlib.import_module("rewindsafe.workflows.rewindsafe")


def _identity(identity_id: str) -> Identity:
    from rewindsafe.runtime import identities

    identity = identities.get_identity(identity_id)
    if identity is None:
        raise SystemExit(f"Unknown demo identity '{identity_id}'.")
    return identity


# ─── commands ──────────────────────────────────────────────────────────────


def cmd_migrate(_: argparse.Namespace) -> int:
    from rewindsafe.runtime import db

    applied = db.apply_migrations()
    bootstrap()
    print(f"Migrations applied: {', '.join(applied) if applied else 'none (already up to date)'}")
    print("Database ready; fixture seeded.")
    return EXIT_OK


def cmd_reset(_: argparse.Namespace) -> int:
    from rewindsafe.api.routes_admin import reset_fixture

    bootstrap()
    print(f"Fixture reset. New generation: {reset_fixture('cli')}")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    from rewindsafe.api.status import build_system_status

    try:
        bootstrap()
    except Exception as exc:  # report, do not crash: status is a diagnostic
        print(paint(f"Startup check failed: {type(exc).__name__}: {exc}", "38;5;196"))
    info = build_system_status()
    if args.json:
        print(json.dumps(info, indent=2))
        return EXIT_OK
    enf, planner = info["enforcement"], info["planner"]
    mode = "SIMULATED (offline)" if enf["simulated"] else "LIVE"
    print(bold("RewindSafe status"))
    print(f"  ArmorIQ enforcement : {mode}; sdk {enf['sdk_version'] or 'n/a'}; session mode {enf['session_mode']}")
    print(f"  Agent planner       : {planner.get('label') or planner['kind']} ({planner['name']})")
    ready = enf.get("readiness") or {}
    if ready:
        print(f"  ArmorIQ readiness   : {ready.get('state')}")
    print(f"  Database            : {'ok' if info['database']['ok'] else 'UNREACHABLE'}")
    print(f"  Fixture generation  : {info['fixture_generation']}")
    print(f"  Contract version    : {info['contract_version']}")
    for warning in info["warnings"]:
        text = warning["message"] if isinstance(warning, dict) else str(warning)
        level = warning.get("level", "warn") if isinstance(warning, dict) else "warn"
        color = {"info": "2", "error": "38;5;196"}.get(level, "38;5;214")
        print(paint(f"  {'i' if level == 'info' else '!'} {text}", color))
    return EXIT_OK if info["database"]["ok"] else EXIT_RUN_FAILED


def _find_scenario(adapter: Any, scenario_id: str) -> Any:
    scenarios = {s.scenario_id: s for s in adapter.scenarios()}
    if scenario_id not in scenarios:
        raise SystemExit(f"Unknown scenario '{scenario_id}'. Choose from: {', '.join(sorted(scenarios))}")
    return scenarios[scenario_id]


def _handle_approval(event: RunEvent, approve: bool, reviewer: Identity, announce: Callable[[str], None]) -> None:
    from rewindsafe.runtime import approvals

    approval = (event.data or {}).get("approval") or {}
    approval_id = approval.get("approval_id")
    if not approval_id:
        return
    verb = "approve" if approve else "reject"
    announce(f"Second reviewer {reviewer.name} will {verb} approval {approval_id} "
             f"(payload {str(approval.get('payload_digest', ''))[:19]}...)")
    time.sleep(1.0)  # let the audience read the request before it is decided
    try:
        approvals.decide(approval_id, reviewer, verb, "Decided from the CLI demo")  # type: ignore[arg-type]
    except Exception as exc:
        announce(paint(f"Could not {verb} the approval: {type(exc).__name__}: {exc}", "38;5;196"))


def stream_run(
    run_id: str,
    *,
    decision: str | None,
    timeout_s: float,
    poll_s: float = 0.3,
) -> bool:
    """Print events until ``run.finished``. Returns True if the run finished in time."""
    from rewindsafe.runtime import events

    reviewer = _identity("dev")
    last_seq = 0
    deadline = time.monotonic() + timeout_s
    hinted = False

    def announce(text: str) -> None:
        print(paint("  >>> " + text, "38;5;211"))

    while True:
        batch = events.list_events(run_id, last_seq)
        finished = False
        for event in batch:
            print(render_event(event), flush=True)
            last_seq = event.seq
            if event.type == "approval.requested":
                if decision:
                    _handle_approval(event, decision == "approve", reviewer, announce)
                elif not hinted:
                    hinted = True
                    announce("Waiting for a second reviewer. Decide in the UI as Orion, or rerun with --approve / --reject.")
            if event.type == "run.finished":
                finished = True
        if finished:
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(poll_s)


def print_summary(run_id: str, tenant_id: str) -> tuple[Any, list[Any]]:
    from rewindsafe.api import queries
    from rewindsafe.api.deps import get_workflow_adapter
    from rewindsafe.runtime import receipts

    found = queries.get_run_with_tenant(run_id)
    run = found[0] if found else None
    checks = get_workflow_adapter().protected_checks(tenant_id)
    print()
    print(bold("Run summary"))
    if run:
        print(f"  Status   : {bold(run.status.value)}  (planner {run.planner}, enforcement {run.enforcement_mode})")
        if run.outcome_summary:
            print(f"  Outcome  : {run.outcome_summary}")
    try:
        metrics = receipts.run_metrics(run_id)
        by_layer = {k: v for k, v in (metrics.get("blocked_by_layer") or {}).items() if v}
        print(f"  Proposals: {metrics.get('proposals')}  executed {metrics.get('executed')}  "
              f"commits {metrics.get('commits')}  replans {metrics.get('replans')}")
        print(f"  Blocked by layer: {by_layer or 'none'}")
        print(f"  Forbidden effects observed: {metrics.get('forbidden_effects_observed')}  "
              f"prohibited handler entries: {metrics.get('prohibited_handler_entries')}")
    except Exception as exc:  # metrics are informative; never hide the protected checks
        print(dim(f"  (metrics unavailable: {type(exc).__name__})"))
    print(bold("Protected checks"))
    for check in checks:
        print(f"  {status_chip(check.status)} {check.label}")
    return run, checks


def cmd_demo(args: argparse.Namespace) -> int:
    from rewindsafe.api.deps import agent_api, get_workflow_adapter, resolve_planner
    from rewindsafe.api.routes_admin import reset_fixture
    from rewindsafe.runtime import grants

    bootstrap()
    adapter = get_workflow_adapter()
    scenario = _find_scenario(adapter, args.scenario)
    maya = _identity("maya")
    if args.reset:
        print(dim(f"Resetting the disposable fixture (generation {reset_fixture('cli')})."))
    decision = "approve" if args.approve else "reject" if args.reject else None
    if decision and scenario.scenario_id != "review":
        print(paint("Note: --approve/--reject only apply to the review scenario.", "38;5;214"))

    print(bold(f"{scenario.title}") + dim(f"  [{scenario.scenario_id}]"))
    print(dim(scenario.tagline))
    grant = grants.create_draft(adapter, scenario, maya)
    print(f"Grant {grant.grant_id} drafted for {maya.name}: tools {', '.join(grant.allowed_tools)}")
    grant = grants.authorize(grant.grant_id, maya)
    print(f"Grant authorized by {maya.name}; digest {grant.grant_digest[:19]}...")
    planner = resolve_planner(args.planner, scenario.default_planner)
    run = agent_api().start_run(grant.grant_id, maya, planner=planner)
    print(f"Run {run.run_id} started ({run.planner}, enforcement {run.enforcement_mode})\n")

    try:
        finished = stream_run(run.run_id, decision=decision, timeout_s=args.timeout)
    except KeyboardInterrupt:
        print("\nInterrupted; cancelling the run.")
        try:
            agent_api().cancel_run(run.run_id, maya)
        except Exception:
            pass
        return EXIT_INTERRUPTED
    final_run, checks = print_summary(run.run_id, grant.tenant_id)
    if any(c.status == InvariantStatus.VIOLATED for c in checks):
        print(paint("\nPROTECTED STATE VIOLATED. This must never happen.", "38;5;196;1"))
        return EXIT_VIOLATED
    if not finished:
        print(paint(f"\nTimed out after {args.timeout:.0f}s waiting for the run to finish.", "38;5;196"))
        return EXIT_RUN_FAILED
    if final_run is not None and final_run.status == RunStatus.FAILED:
        return EXIT_RUN_FAILED
    if final_run is not None and final_run.status not in TERMINAL_RUN_STATUSES:
        return EXIT_RUN_FAILED
    print(paint("\nAll protected checks hold.", "38;5;78"))
    return EXIT_OK


def cmd_mcp_agent(args: argparse.Namespace) -> int:
    """Run VeerIQ's agent against the rewindsafe-recovery MCP server: every action is an MCP tools/call."""
    import anyio

    from rewindsafe.agent.mcp_agent import run_mcp_agent, stdio_server
    from rewindsafe.api.deps import get_workflow_adapter
    from rewindsafe.api.routes_admin import reset_fixture
    from rewindsafe.runtime import grants

    bootstrap()
    adapter = get_workflow_adapter()
    scenario = _find_scenario(adapter, args.scenario)
    if scenario.kind == "boundary":
        print(paint("The boundary harness runs in-process; use clean, poisoned or review here.", "38;5;196"))
        return EXIT_RUN_FAILED
    maya = _identity("maya")
    if args.reset:
        print(dim(f"Resetting the disposable fixture (generation {reset_fixture('cli')})."))
    print(bold(f"{scenario.title} over MCP") + dim(f"  [{scenario.scenario_id}]"))
    grant = grants.authorize(grants.create_draft(adapter, scenario, maya).grant_id, maya)
    print(f"Grant {grant.grant_id} authorized by {maya.name}: tools {', '.join(grant.allowed_tools)}")
    server: Any = args.url if args.url else stdio_server(grant.grant_id)
    if args.url:
        print(dim(f"Connecting to the MCP server at {args.url} (it must serve grant {grant.grant_id})."))
    else:
        print(dim("Spawning the rewindsafe-recovery MCP server over stdio (it binds the signed ArmorIQ plan)."))
    try:
        result = anyio.run(lambda: run_mcp_agent(server, grant, scenario, adapter, planner=args.planner))
    except KeyboardInterrupt:
        print("\nInterrupted; the MCP server closes the run when its session ends.")
        return EXIT_INTERRUPTED
    if not result.run_id:
        print(paint("The agent made no tool call, so the MCP server recorded no run.", "38;5;196"))
        return EXIT_RUN_FAILED
    blocked = [s for s in result.steps if s.status != "executed" and s.status != "duplicate"]
    allowed = [s for s in result.steps if s not in blocked]
    print(f"\nRun {result.run_id}: {len(allowed)} MCP call(s) allowed, {len(blocked)} refused.")
    _, checks = print_summary(result.run_id, grant.tenant_id)
    if any(c.status == InvariantStatus.VIOLATED for c in checks):
        print(paint("\nPROTECTED STATE VIOLATED. This must never happen.", "38;5;196;1"))
        return EXIT_VIOLATED
    print(paint("\nAll protected checks hold.", "38;5;78"))
    return EXIT_OK


def cmd_verify(_: argparse.Namespace) -> int:
    import importlib

    from rewindsafe.runtime import canonical

    bootstrap()
    suite = importlib.import_module("rewindsafe.verification.suite")
    verification_id = canonical.new_id("ver")
    print(bold(f"Running verification suite {verification_id} (fresh fixture generation per check)..."))
    result = suite.run_suite(verification_id)
    result = dict(result)
    result.setdefault("verification_id", verification_id)

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = EVIDENCE_DIR / f"verification-{stamp}.json"
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    checks = result.get("results") or []
    for check in checks:
        mark = paint("PASS", "38;5;78") if check.get("passed") else paint("FAIL", "38;5;196;1")
        print(f"  {mark}  {check.get('check_id', '?'):<34} {check.get('layer_actual') or ''}  "
              f"{dim(str(check.get('title', '')))}")
    status = result.get("status")
    print(f"\nStatus: {bold(str(status))}  summary: {json.dumps(result.get('summary', {}), default=str)}")
    print(f"Evidence written to {path}")
    if status == "blocked":
        print(paint("BLOCKED: verification could not run to completion (see summary). Not a pass.", "38;5;196;1"))
        return EXIT_BLOCKED
    return EXIT_OK if status == "passed" and all(c.get("passed") for c in checks) else EXIT_VIOLATED


def cmd_evidence(args: argparse.Namespace) -> int:
    from rewindsafe.runtime import receipts

    bootstrap()
    evidence = receipts.build_evidence(args.run)
    out = Path(args.out) if args.out else EVIDENCE_DIR / f"run-{args.run}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(f"Evidence for {args.run} written to {out}")
    return EXIT_OK


# ─── entry point ───────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rewindsafe", description="RewindSafe command line")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="apply migrations and seed the fixture").set_defaults(func=cmd_migrate)
    sub.add_parser("reset", help="reset the disposable demo fixture").set_defaults(func=cmd_reset)

    status = sub.add_parser("status", help="show enforcement/planner/database status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    demo = sub.add_parser("demo", help="run a scenario end to end in-process")
    demo.add_argument("--scenario", required=True, help="poisoned | clean | stale | review | boundary")
    demo.add_argument("--planner", choices=["auto", "scripted", "llm"], default="auto")
    group = demo.add_mutually_exclusive_group()
    group.add_argument("--approve", action="store_true", help="review scenario: Orion approves the request")
    group.add_argument("--reject", action="store_true", help="review scenario: Orion rejects the request")
    demo.add_argument("--no-reset", dest="reset", action="store_false", help="keep the current fixture state")
    demo.add_argument("--timeout", type=float, default=300.0, help="seconds to wait for the run (default 300)")
    demo.set_defaults(func=cmd_demo, reset=True)

    mcp = sub.add_parser("mcp-agent", help="run the agent against the MCP server (every action is an MCP call)")
    mcp.add_argument("scenario", nargs="?", default="poisoned", help="poisoned | clean | review")
    mcp.add_argument("--planner", choices=["auto", "scripted", "llm"], default="auto")
    mcp.add_argument("--url", help="streamable-HTTP MCP endpoint instead of spawning the server over stdio")
    mcp.add_argument("--no-reset", dest="reset", action="store_false", help="keep the current fixture state")
    mcp.set_defaults(func=cmd_mcp_agent, reset=True)

    sub.add_parser("verify", help="run the verification suite, write evidence/verification-<UTC>.json").set_defaults(
        func=cmd_verify
    )

    evidence = sub.add_parser("evidence", help="export the evidence bundle for a run")
    evidence.add_argument("--run", required=True, help="run id")
    evidence.add_argument("--out", help="output path (default evidence/run-<id>.json)")
    evidence.set_defaults(func=cmd_evidence)
    return parser


def main(argv: list[str] | None = None) -> int:
    _init_terminal()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
