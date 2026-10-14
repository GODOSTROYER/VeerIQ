"""CLI helpers: parser, event rendering and the approval-driving stream loop."""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime
from types import ModuleType

import pytest


def _ensure_module(name: str) -> None:
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        module = ModuleType(name)
        sys.modules[name] = module
        parent, _, child = name.rpartition(".")
        setattr(importlib.import_module(parent), child, module)


for _name in ("rewindsafe.runtime.grants", "rewindsafe.runtime.approvals", "rewindsafe.runtime.receipts",
              "rewindsafe.runtime.armoriq_gateway"):
    _ensure_module(_name)

from rewindsafe import cli
from rewindsafe.contracts import Actor, Decision, DecisionSource, Layer, Outcome, RunEvent
from rewindsafe.runtime import approvals, events

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def event(seq, type_, title="t", **kw):
    return RunEvent(seq=seq, run_id="run_1", ts=NOW, type=type_, actor=kw.pop("actor", Actor.SYSTEM), title=title, **kw)


def test_parser_accepts_documented_invocations():
    parser = cli.build_parser()
    args = parser.parse_args(["demo", "--scenario", "review", "--approve", "--planner", "scripted"])
    assert args.approve and not args.reject and args.planner == "scripted" and args.reset is True
    assert parser.parse_args(["demo", "--scenario", "clean", "--no-reset"]).reset is False
    assert parser.parse_args(["evidence", "--run", "run_1", "--out", "x.json"]).out == "x.json"
    for command in ("migrate", "reset", "verify", "status"):
        assert parser.parse_args([command]).command == command
    with pytest.raises(SystemExit):
        parser.parse_args(["demo", "--scenario", "review", "--approve", "--reject"])


def test_render_decision_event_labels_simulated_and_layer():
    decision = Decision(
        decision_id="d1", run_id="run_1", layer=Layer.ARMORIQ, source=DecisionSource.ARMORIQ_SIMULATED,
        outcome=Outcome.BLOCK, simulated=True, reason="not in plan", created_at=NOW,
    )
    text = cli.render_event(event(1, "decision", "ArmorIQ blocked restore_access_grant", decision=decision,
                                  detail="Not in the signed recovery plan.", actor=Actor.ARMORIQ))
    assert "ARMORIQ" in text and "BLOCK" in text and "SIMULATED" in text and "signed recovery plan" in text


def test_stream_run_decides_approval_and_stops_at_finish(monkeypatch, capsys):
    batches = [
        [event(1, "agent.note", "starting")],
        [event(2, "approval.requested", "Review needed",
               data={"approval": {"approval_id": "apr_1", "payload_digest": "sha256:" + "a" * 64}})],
        [event(3, "run.finished", "done")],
    ]
    monkeypatch.setattr(events, "list_events", lambda run_id, after: batches.pop(0) if batches else [])
    decided = []
    monkeypatch.setattr(approvals, "decide", lambda aid, who, verdict, note="": decided.append((aid, who.identity_id, verdict)),
                        raising=False)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    assert cli.stream_run("run_1", decision="approve", timeout_s=5, poll_s=0) is True
    assert decided == [("apr_1", "dev", "approve")]
    assert "done" in capsys.readouterr().out


def test_stream_run_without_decision_prints_hint_and_times_out(monkeypatch, capsys):
    monkeypatch.setattr(events, "list_events", lambda run_id, after: [
        event(1, "approval.requested", "Review needed", data={"approval": {"approval_id": "apr_1"}})
    ] if after == 0 else [])
    decided = []
    monkeypatch.setattr(approvals, "decide", lambda *a, **k: decided.append(a), raising=False)
    assert cli.stream_run("run_1", decision=None, timeout_s=0.05, poll_s=0.01) is False
    assert not decided and "Waiting for a second reviewer" in capsys.readouterr().out
