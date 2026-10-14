"""End-to-end scenario runs through the real agent loop (scripted planner, offline gateway)."""

from __future__ import annotations

import pytest

from rewindsafe.contracts import RunStatus
from rewindsafe.verification import checks

# (scenario, planner, auto-review decision, expected status, expected commits)
CASES = [
    ("clean", "scripted", None, RunStatus.SUCCEEDED, 1),
    ("poisoned", "scripted", None, RunStatus.SUCCEEDED, 1),
    ("stale", "scripted", None, RunStatus.PARTIALLY_SUCCEEDED, 1),
    ("review", "scripted", "approve", RunStatus.SUCCEEDED, 1),
    ("review", "scripted", "reject", RunStatus.BLOCKED, 0),
    ("boundary", "auto", None, RunStatus.SUCCEEDED, 1),
]


@pytest.mark.parametrize(
    "scenario,planner,review,expected_status,expected_commits",
    CASES,
    ids=[f"{c[0]}-{c[2]}" if c[2] else c[0] for c in CASES],
)
def test_scenario_runs_to_terminal_status(test_db, scenario, planner, review, expected_status, expected_commits):
    from rewindsafe.runtime import receipts

    checks.reset_fixture_state("tests")
    run = checks.run_scenario(scenario, planner=planner, review=review, timeout=60)
    facts = checks.run_facts(run.run_id)

    assert run.status == expected_status, (run.status, run.outcome_summary, facts["timeline"])
    assert facts["commits"] == expected_commits, facts["timeline"]
    # The privileged handler must never have been entered by any run.
    assert facts["prohibited_handler_entries"] == 0
    # Protected authority is never violated.
    assert checks.violated() == []
    assert checks.ag77_status() == "revoked"
    metrics = receipts.run_metrics(run.run_id)
    assert metrics.get("forbidden_effects_observed", 0) == 0
    assert metrics.get("prohibited_handler_entries", 0) == 0


def test_boundary_run_every_probe_passed(test_db):
    """The boundary run must not only finish: all 12 probes must have passed (no hollow success)."""
    from rewindsafe.agent import loop

    checks.reset_fixture_state("tests")
    run = checks.run_scenario("boundary", planner="auto", timeout=90)
    run = loop.get_run(run.run_id)
    probes = (run.metadata or {}).get("probes", [])
    failing = [(p.get("probe_id"), p.get("title"), p.get("actual_layer"), p.get("actual_source"), p.get("outcome"))
               for p in probes if not p.get("passed")]
    assert len(probes) == 12, f"expected 12 probes, got {len(probes)}"
    assert not failing, f"failing probes: {failing}"


def test_inspect_snapshot_event_keeps_full_redacted_annotations(test_db, monkeypatch):
    from rewindsafe.contracts import DecisionSource, DispatchStatus, Outcome
    from rewindsafe.runtime import events
    from rewindsafe.runtime.canonical import canonical_json, redact_secrets
    from rewindsafe.workflows import rewindsafe as workflow

    captured = []
    execute = workflow.ADAPTER.execute

    def capture_handler_observation(ctx, tool, args):
        result = execute(ctx, tool, args)
        if tool == "inspect_snapshot" and result.status == DispatchStatus.EXECUTED:
            note = "historical annotation " * 40 + "ak_live_TESTSECRET continued through the full note"
            result.observation["annotations"][0]["body"] = note
            captured.append(result.observation["annotations"])
        return result

    monkeypatch.setattr(workflow.ADAPTER, "execute", capture_handler_observation)
    checks.reset_fixture_state("tests")
    run = checks.run_scenario("poisoned", planner="scripted")
    timeline = events.list_events(run.run_id)
    result_event = next(
        event
        for event in timeline
        if event.type == "tool.result" and event.data.get("tool") == "inspect_snapshot"
    )

    assert len(captured) == 1
    assert result_event.data["annotations"] == redact_secrets(captured[0])
    assert result_event.data["annotations"][0]["body"].endswith("continued through the full note")
    assert len(result_event.data["annotations"][0]["body"]) > 600
    assert "ak_live_TESTSECRET" not in canonical_json(result_event.data["annotations"])

    inspect_decision = next(
        event.decision
        for event in timeline
        if event.type == "decision" and event.proposal_id == result_event.proposal_id and event.decision
    )
    assert inspect_decision.outcome == Outcome.ALLOW
    assert inspect_decision.source == DecisionSource.ARMORIQ_SIMULATED
    assert inspect_decision.simulated is True
