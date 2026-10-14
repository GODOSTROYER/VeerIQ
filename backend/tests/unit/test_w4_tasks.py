"""tasks.py: command wiring and the test-live BLOCKED contract (no subprocesses are spawned)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

TASKS_PATH = Path(__file__).resolve().parents[3] / "tasks.py"


@pytest.fixture()
def tasks():
    spec = importlib.util.spec_from_file_location("rewindsafe_tasks", TASKS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_command_is_documented_and_callable(tasks):
    assert set(tasks.COMMANDS) == set(tasks.DOCS)
    assert {"setup", "up", "backend", "frontend", "build", "test", "test-live", "demo-normal",
            "demo-agent-attack", "demo-boundary", "demo-stale", "demo-review", "reset-demo",
            "eval-reliability", "verify", "down"} <= set(tasks.COMMANDS)
    assert all(callable(c) for c in tasks.COMMANDS.values())


def test_demo_commands_map_to_scenarios(tasks, monkeypatch):
    seen = []
    monkeypatch.setattr(tasks, "cli", lambda *args: seen.append(args) or 0)
    for name in ("demo-normal", "demo-agent-attack", "demo-boundary", "demo-stale", "demo-review"):
        assert tasks.main([name]) == 0
    assert seen == [
        ("demo", "--scenario", "clean"),
        ("demo", "--scenario", "poisoned", "--planner", "auto"),
        ("demo", "--scenario", "boundary"),
        ("demo", "--scenario", "stale"),
        ("demo", "--scenario", "review", "--approve"),
    ]


def test_reliability_eval_forwards_arguments_to_backend_module(tasks, monkeypatch):
    seen = []
    monkeypatch.setattr(tasks, "uv_run", lambda *args, **kwargs: seen.append((args, kwargs)) or 0)
    assert tasks.main(["eval-reliability", "--trials", "1", "--models", "openai/gpt-oss-120b"]) == 0
    assert seen[0][0] == (
        "python", "-m", "rewindsafe.agent.reliability_eval", "--trials", "1", "--models", "openai/gpt-oss-120b"
    )


def test_unknown_command_is_nonzero(tasks):
    assert tasks.main(["nope"]) != 0
    assert tasks.main(["help"]) == 0


def patch_live(tasks, monkeypatch, *, key: bool, results: list[int]):
    monkeypatch.setattr(tasks, "_find_probe", lambda: Path("probe.py"))
    monkeypatch.setattr(tasks, "_env_file_has_key", lambda: key)
    monkeypatch.delenv("ARMORIQ_API_KEY", raising=False)
    calls = []

    def fake_uv_run(*args, **_):
        calls.append(args)
        return results.pop(0)

    monkeypatch.setattr(tasks, "uv_run", fake_uv_run)
    return calls


def test_live_blocked_when_probe_reports_missing_key(tasks, monkeypatch):
    calls = patch_live(tasks, monkeypatch, key=False, results=[2])
    assert tasks.cmd_test_live([]) == 2
    assert len(calls) == 1  # pytest -m live never runs


def test_live_never_succeeds_without_a_key_even_if_probe_returns_zero(tasks, monkeypatch):
    calls = patch_live(tasks, monkeypatch, key=False, results=[0])
    assert tasks.cmd_test_live([]) == 2
    assert len(calls) == 1


def test_live_success_requires_key_probe_and_pytest(tasks, monkeypatch):
    calls = patch_live(tasks, monkeypatch, key=True, results=[0, 0])
    assert tasks.cmd_test_live([]) == 0
    assert calls[1][:3] == ("pytest", "-m", "live")


def test_live_propagates_failures_and_empty_collection(tasks, monkeypatch):
    patch_live(tasks, monkeypatch, key=True, results=[1])
    assert tasks.cmd_test_live([]) == 1
    patch_live(tasks, monkeypatch, key=True, results=[0, 1])
    assert tasks.cmd_test_live([]) == 1
    patch_live(tasks, monkeypatch, key=True, results=[0, 5])
    assert tasks.cmd_test_live([]) == 1  # nothing collected is not a pass


def test_env_file_key_detection(tasks, monkeypatch):
    import tempfile

    with tempfile.TemporaryDirectory() as name:
        monkeypatch.setattr(tasks, "ROOT", Path(name))
        assert tasks._env_file_has_key() is False
        (Path(name) / ".env").write_text("ARMORIQ_API_KEY=\nOTHER=1\n")
        assert tasks._env_file_has_key() is False
        (Path(name) / ".env").write_text("ARMORIQ_API_KEY=ak_test_abc\n")
        assert tasks._env_file_has_key() is True
