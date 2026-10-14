#!/usr/bin/env python3
"""RewindSafe task runner (stdlib only, cross-platform).

    python tasks.py <command> [args]

Run ``python tasks.py help`` for the list. The Makefile is a thin wrapper.
Exit codes are propagated from the underlying tools. ``test-live`` exits 2
("BLOCKED") when ArmorIQ credentials are missing: that is never a pass.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
IS_WINDOWS = os.name == "nt"

BACKEND_HOST, BACKEND_PORT = "127.0.0.1", 8020
FRONTEND_HOST, FRONTEND_PORT = "127.0.0.1", 5173

EXIT_BLOCKED = 2

RESET = "\033[0m"


def _color(code: str, text: str) -> str:
    return f"\033[{code}m{text}{RESET}" if sys.stdout.isatty() else text


def info(msg: str) -> None:
    print(_color("1;36", f"==> {msg}"), flush=True)


def fail(msg: str, code: int = 1) -> int:
    print(_color("1;31", msg), file=sys.stderr, flush=True)
    return code


def require(tool: str) -> str:
    """Resolve an executable on PATH (handles npm.cmd on Windows) or exit with a hint."""
    found = shutil.which(tool)
    if not found:
        hints = {
            "uv": "Install uv: https://docs.astral.sh/uv/",
            "docker": "Install Docker Desktop and make sure it is running.",
            "npm": "Install Node.js (includes npm).",
        }
        raise SystemExit(fail(f"'{tool}' was not found on PATH. {hints.get(tool, '')}".strip()))
    return found


def run(cmd: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None) -> int:
    info(f"{' '.join(cmd)}   (in {cwd.relative_to(ROOT) if cwd != ROOT else '.'})")
    merged = {**os.environ, **(env or {})}
    return subprocess.call(cmd, cwd=cwd, env=merged)


def uv_run(*args: str, extra_env: dict[str, str] | None = None) -> int:
    return run([require("uv"), "run", *args], cwd=BACKEND, env=extra_env)


def cli(*args: str) -> int:
    return uv_run("python", "-m", "rewindsafe.cli", *args)


# ─── commands ──────────────────────────────────────────────────────────────


def cmd_setup(_: list[str]) -> int:
    """Start Postgres, install dependencies, migrate and seed."""
    env_file, example = ROOT / ".env", ROOT / ".env.example"
    if not env_file.is_file() and example.is_file():
        shutil.copyfile(example, env_file)
        info("Created .env from .env.example (add keys there; never commit it)")
    steps: list[tuple[str, list[str], Path]] = [
        ("Start Postgres", [require("docker"), "compose", "up", "-d", "--wait"], ROOT),
        ("Install backend dependencies", [require("uv"), "sync"], BACKEND),
        ("Install frontend dependencies", [require("npm"), "install"], FRONTEND),
    ]
    for title, cmd, cwd in steps:
        info(title)
        code = run(cmd, cwd=cwd)
        if code:
            return code
    info("Migrate and seed the database")
    code = cli("migrate")
    if code:
        return code
    _describe_modes()
    return 0


def _describe_modes() -> None:
    """Say which modes the current .env will produce (no secret values are printed)."""
    live_enforcement = bool(_setting("ARMORIQ_API_KEY"))
    live_llm = any(_setting(k) for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY"))
    info("Enforcement: " + ("LIVE ArmorIQ (key present; run `python tasks.py armoriq-register` once per workspace)"
                            if live_enforcement else "SIMULATED offline (no ARMORIQ_API_KEY)"))
    info("Planner: " + ("live LLM (a provider key is present)" if live_llm
                        else "scripted deterministic re-enactment (no LLM key)"))


def _backend_cmd(reload: bool) -> list[str]:
    cmd = [require("uv"), "run", "uvicorn", "rewindsafe.api.app:app", "--host", BACKEND_HOST,
           "--port", str(BACKEND_PORT)]
    return cmd + (["--reload"] if reload else [])


def _frontend_cmd() -> list[str]:
    return [require("npm"), "run", "dev", "--", "--host", FRONTEND_HOST, "--port", str(FRONTEND_PORT),
            "--strictPort"]


def cmd_backend(args: list[str]) -> int:
    """API on http://127.0.0.1:8020 (add --reload for auto-reload)."""
    return run(_backend_cmd("--reload" in args), cwd=BACKEND)


def _need_frontend() -> int | None:
    if not (FRONTEND / "package.json").is_file():
        return fail("frontend/package.json is missing; the frontend has not been created yet.")
    return None


def cmd_frontend(_: list[str]) -> int:
    """Vite dev server on http://127.0.0.1:5173 (proxies /api to :8020)."""
    return _need_frontend() or run(_frontend_cmd(), cwd=FRONTEND)


def _spawn(cmd: list[str], cwd: Path) -> subprocess.Popen:
    info(f"{' '.join(cmd)}   (in {cwd.name})")
    if IS_WINDOWS:
        return subprocess.Popen(cmd, cwd=cwd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(cmd, cwd=cwd, start_new_session=True)


def _stop(proc: subprocess.Popen) -> None:
    """Terminate a child and everything it spawned (uvicorn workers, vite, node)."""
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            subprocess.call(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired, OSError):
        proc.kill()


def cmd_up(args: list[str]) -> int:
    """Backend (:8020) and frontend (:5173) together. Ctrl+C stops both."""
    if (code := _need_frontend()) is not None:
        return code
    procs = [_spawn(_backend_cmd("--reload" in args), BACKEND), _spawn(_frontend_cmd(), FRONTEND)]
    print(_color("1;32", f"\nRewindSafe: UI http://localhost:{FRONTEND_PORT}   API http://localhost:{BACKEND_PORT}/docs"
                         "\nPress Ctrl+C to stop both.\n"), flush=True)
    exit_code = 0
    try:
        while True:
            for proc in procs:
                code = proc.poll()
                if code is not None:
                    print(_color("1;31", f"A server exited with code {code}; stopping the other."), flush=True)
                    exit_code = code or 1
                    raise StopIteration
            time.sleep(0.5)
    except StopIteration:
        pass
    except KeyboardInterrupt:
        print("\nStopping...", flush=True)
    finally:
        for proc in procs:
            _stop(proc)
    return exit_code


def cmd_build(_: list[str]) -> int:
    """Production build of the frontend (served by the API at / when present)."""
    return _need_frontend() or run([require("npm"), "run", "build"], cwd=FRONTEND)


def cmd_test(args: list[str]) -> int:
    """Backend test suite (real Postgres, offline gateway)."""
    return uv_run("pytest", *args)


def cmd_restore_risk(args: list[str]) -> int:
    return uv_run("python", str(ROOT / "scripts" / "restore_risk.py"), *args)


def _find_probe() -> Path | None:
    for candidate in (BACKEND / "scripts" / "armoriq_probe.py", ROOT / "scripts" / "armoriq_probe.py"):
        if candidate.is_file():
            return candidate
    return None


def _env_file_has_key() -> bool:
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return False
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == "ARMORIQ_API_KEY" and value.strip().strip("'\""):
            return True
    return False


def _read_env_file() -> dict[str, str]:
    """Parse ROOT/.env (KEY=VALUE lines) without logging any value."""
    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return values
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if sep:
            values[name.strip()] = value.strip().strip("'\"")
    return values


def _setting(name: str, default: str = "") -> str:
    return (os.environ.get(name) or _read_env_file().get(name) or default).strip()


def _blocked(reason: str) -> int:
    bar = "=" * 72
    print(_color("1;31", f"\n{bar}\nBLOCKED: live ArmorIQ verification did NOT run.\n{reason}\n"
                         "This is not a pass. Set ARMORIQ_API_KEY (ak_test_... / ak_live_...) in .env and rerun.\n"
                         f"{bar}"), file=sys.stderr, flush=True)
    return EXIT_BLOCKED


def cmd_test_live(args: list[str]) -> int:
    """Gate A: probe the real ArmorIQ service, then run `pytest -m live`. Never passes without a key."""
    has_key = bool(os.environ.get("ARMORIQ_API_KEY", "").strip()) or _env_file_has_key()
    probe = _find_probe()
    if probe is None:
        return fail("scripts/armoriq_probe.py was not found (looked in backend/scripts and scripts).")
    code = uv_run("python", str(probe))
    if code == EXIT_BLOCKED:
        return _blocked("The probe reported that ArmorIQ credentials or connectivity are missing.")
    if code:
        return fail(f"ArmorIQ probe failed with exit code {code}.", code)
    if not has_key:
        return _blocked("No ARMORIQ_API_KEY in the environment or .env, so nothing was verified live.")
    code = uv_run("pytest", "-m", "live", *args)
    if code == 5:
        return fail("No live tests were collected; refusing to report success.", 1)
    if code:
        return fail(f"Live tests failed (exit code {code}).", code)
    print(_color("1;32", "Live ArmorIQ verification passed."), flush=True)
    return 0


def cmd_live_evidence(args: list[str]) -> int:
    """Run the live ArmorIQ probe and write evidence/gate-a-<UTC>.json (exit 2 = BLOCKED, never a pass)."""
    probe = _find_probe()
    if probe is None:
        return fail("scripts/armoriq_probe.py was not found (looked in backend/scripts and scripts).")
    code = uv_run("python", str(probe), *args)
    if code == EXIT_BLOCKED:
        return _blocked("The probe reported that ArmorIQ credentials or connectivity are missing.")
    return code


def cmd_eval_injection(args: list[str]) -> int:
    """Prompt-injection eval: which Groq models propose restore_access_grant (writes evidence/injection-eval-<UTC>.json)."""
    return uv_run("python", "-m", "rewindsafe.agent.injection_eval", *args)


def cmd_eval_reliability(args: list[str]) -> int:
    """End-to-end poisoned recovery reliability eval (live Groq + ArmorIQ; isolated DB; resumable evidence)."""
    return uv_run("python", "-m", "rewindsafe.agent.reliability_eval", *args)


def cmd_armoriq_register(args: list[str]) -> int:
    """Register this agent and its policy in YOUR ArmorIQ workspace (needs ARMORIQ_API_KEY + ARMORIQ_USER_EMAIL in .env)."""
    template = ROOT / "armoriq" / "armoriq.yaml"
    api_key, email = _setting("ARMORIQ_API_KEY"), _setting("ARMORIQ_USER_EMAIL")
    agent_id = _setting("ARMORIQ_AGENT_ID", "rewindsafe-recovery-agent")
    missing = [n for n, v in (("ARMORIQ_API_KEY", api_key), ("ARMORIQ_USER_EMAIL", email)) if not v]
    if missing:
        return fail(f"Set {' and '.join(missing)} in .env first (the email is the account that owns the key).", 2)
    if not template.is_file():
        return fail("armoriq/armoriq.yaml (the registration template) is missing.")
    rendered = (template.read_text(encoding="utf-8")
                .replace("${ARMORIQ_USER_EMAIL}", email)
                .replace("${ARMORIQ_AGENT_ID}", agent_id))
    tmp_dir = Path(tempfile.mkdtemp(prefix="rewindsafe-armoriq-"))
    config = tmp_dir / "armoriq.yaml"
    config.write_text(rendered, encoding="utf-8")
    try:
        code = uv_run("armoriq", "register", "--config", str(config), *args,
                      extra_env={"ARMORIQ_API_KEY": api_key, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    if code:
        return fail(f"armoriq register failed (exit {code}). Check the key, the email and connectivity.", code)
    print(_color("1;32", "Registered: the allowlist (5 recovery tools allowed, restore_access_grant denied) is now "
                         "active in your workspace."), flush=True)
    print("Optional, dashboard only: add an amount threshold on apply_repair_manifest "
          "(approve above $5,000) to get an ArmorIQ HOLD. See docs/runbook.md.", flush=True)
    return 0


def _demo(scenario: str, *extra: str):
    def command(args: list[str]) -> int:
        return cli("demo", "--scenario", scenario, *extra, *args)

    return command


def cmd_reset_demo(_: list[str]) -> int:
    """Reset the disposable demo fixture (new generation)."""
    return cli("reset")


def cmd_verify(args: list[str]) -> int:
    """Run the verification suite and write evidence/verification-<UTC>.json."""
    return cli("verify", *args)


def cmd_down(_: list[str]) -> int:
    """Stop Postgres (data volume is kept)."""
    return run([require("docker"), "compose", "down"], cwd=ROOT)


COMMANDS = {
    "setup": cmd_setup,
    "up": cmd_up,
    "backend": cmd_backend,
    "frontend": cmd_frontend,
    "build": cmd_build,
    "test": cmd_test,
    "test-live": cmd_test_live,
    "demo-normal": _demo("clean"),
    "demo-agent-attack": _demo("poisoned", "--planner", "auto"),
    "demo-boundary": _demo("boundary"),
    "demo-mcp-agent": lambda args: cli("mcp-agent", *(args or ["poisoned"])),
    "demo-stale": _demo("stale"),
    "demo-review": _demo("review", "--approve"),
    "reset-demo": cmd_reset_demo,
    "armoriq-register": cmd_armoriq_register,
    "live-evidence": cmd_live_evidence,
    "eval-injection": cmd_eval_injection,
    "eval-reliability": cmd_eval_reliability,
    "show-restore-risk": cmd_restore_risk,
    "verify": cmd_verify,
    "down": cmd_down,
}

DOCS = {
    "setup": "start Postgres, install backend + frontend deps, migrate and seed",
    "up": "backend :8020 + frontend :5173 together (Ctrl+C stops both; --reload for backend reload)",
    "backend": "API only (uvicorn on :8020; --reload)",
    "frontend": "Vite dev server only (:5173)",
    "build": "production build of the frontend (the API serves frontend/dist)",
    "test": "backend pytest suite (extra args are passed to pytest)",
    "test-live": "Gate A: ArmorIQ probe + pytest -m live; exits 2 (BLOCKED) without a key",
    "demo-normal": "clean recovery (baseline) in the terminal",
    "demo-agent-attack": "poisoned runbook (live LLM if a key is set, else scripted re-enactment): privileged call blocked, repair completes",
    "demo-mcp-agent": "the same agent driving the rewindsafe-recovery MCP server over stdio: ArmorIQ allows the repair calls and blocks restore_access_grant",
    "demo-boundary": "deterministic boundary harness (forbidden proposals through the real path)",
    "demo-stale": "authority changes mid-repair: stale commit rejected, re-previewed",
    "demo-review": "high-value repair held for a second reviewer (auto-approved by Dev)",
    "reset-demo": "reset the disposable demo fixture",
    "armoriq-register": "register the agent + allowlist in your ArmorIQ workspace (needs ARMORIQ_API_KEY, ARMORIQ_USER_EMAIL)",
    "live-evidence": "run the live ArmorIQ probe; writes evidence/gate-a-<UTC>.json (exit 2 = BLOCKED)",
    "eval-injection": "prompt-injection eval across Groq models; writes evidence/injection-eval-<UTC>.json (needs GROQ_API_KEY)",
    "eval-reliability": "end-to-end poisoned recovery eval (20 trials/model/briefing; live Groq + ArmorIQ; isolated DB; resumable JSON)",
    "show-restore-risk": "read-only fixture comparison: four legitimate decisions reversed by a blunt restore",
    "verify": "run the verification suite; writes evidence/verification-<UTC>.json",
    "down": "stop Postgres",
}


def usage() -> str:
    lines = ["RewindSafe tasks:  python tasks.py <command> [args]", ""]
    lines += [f"  {name:<18} {DOCS[name]}" for name in COMMANDS]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"help", "-h", "--help"}:
        print(usage())
        return 0
    name, rest = argv[0], argv[1:]
    command = COMMANDS.get(name)
    if command is None:
        print(usage(), file=sys.stderr)
        return fail(f"\nUnknown command '{name}'.", 64)
    try:
        return command(rest)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
