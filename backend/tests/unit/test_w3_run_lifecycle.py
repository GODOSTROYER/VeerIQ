"""W3 lifecycle tests: real runs (scripted/harness planners, offline gateway) on the disposable test database.

No LLM and no network. These exercise ``start_run`` -> worker -> dispatcher -> terminal status end to end.
"""

from __future__ import annotations

import time

import pytest

from rewindsafe.agent import cancel_run, get_run, list_runs, start_run
from rewindsafe.contracts import TERMINAL_RUN_STATUSES, Run, RunStatus
from rewindsafe.runtime import approvals, events, grants, mutators
from rewindsafe.runtime.adapter import get_adapter
from rewindsafe.runtime.identities import get_identity

WORKFLOW = "rewindsafe.order_repair"


def _adapter():
    import rewindsafe.workflows.rewindsafe.adapter  # noqa: F401 - registers the adapter

    return get_adapter(WORKFLOW)


def _grant(scenario_id: str):
    adapter = _adapter()
    maya = get_identity("maya")
    scenario = next(s for s in adapter.scenarios() if s.scenario_id == scenario_id)
    draft = grants.create_draft(adapter, scenario, maya)
    return grants.authorize(draft.grant_id, maya), maya


def _wait(run_id: str, timeout: float = 60.0, until=None) -> Run:
    terminal_wait = until is None
    until = until or (lambda r: r.status in TERMINAL_RUN_STATUSES)
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = get_run(run_id)
        if until(run):
            if terminal_wait and "run.finished" not in _types(run_id):
                time.sleep(
                    0.1
                )  # let the worker emit its closing event before the next test resets the fixture
                continue
            return run
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} stuck in {get_run(run_id).status}")


def _types(run_id: str) -> list[str]:
    return [e.type for e in events.list_events(run_id, limit=2000)]


def test_clean_run_succeeds(fresh):
    grant, maya = _grant("clean")
    run = start_run(grant.grant_id, maya, planner="scripted")
    assert run.planner == "scripted" and run.planner_kind == "scripted"
    done = _wait(run.run_id)
    assert done.plan is not None  # bound by the worker, not by start_run
    assert done.status is RunStatus.SUCCEEDED, done.outcome_summary
    assert "Repaired O-2041 and O-2042" in done.outcome_summary
    types = _types(run.run_id)
    assert types[0] == "run.created" and "plan.bound" in types and "plan.requested" in types and [t for t in types if t != "telemetry.delivery"][-1] == "run.finished"
    assert mutators.count_entries("restore_access_grant", run_id=run.run_id) == 0
    assert done.metadata["protected_checks"]["violated"] == 0
    assert any(r.run_id == run.run_id for r in list_runs(10))


def test_supervisor_check_is_preserved_in_timeline_and_evidence(fresh, monkeypatch):
    from rewindsafe.agent import loop
    from rewindsafe.agent.planners import ScriptedPlanner
    from rewindsafe.agent.state import Note
    from rewindsafe.contracts import Actor
    from rewindsafe.runtime.receipts import build_evidence

    message = "Automatic supervisor check: " + "The existing scoped repair is authorized. " * 15

    class VisibleCheckPlanner(ScriptedPlanner):
        def _opening(self, state):
            return [Note(message, actor=Actor.SYSTEM, kind="supervisor_check"), *super()._opening(state)]

    monkeypatch.setattr(loop, "select_planner", lambda *args, **kw: VisibleCheckPlanner())
    grant, maya = _grant("clean")
    done = _wait(start_run(grant.grant_id, maya, planner="scripted").run_id)
    assert done.status is RunStatus.SUCCEEDED
    timeline = [e for e in events.list_events(done.run_id) if e.data.get("kind") == "supervisor_check"]
    assert len(timeline) == 1 and timeline[0].actor is Actor.SYSTEM
    assert timeline[0].detail == message and timeline[0].title.startswith("Automatic supervisor check:")
    exported = [e for e in build_evidence(done.run_id)["events"] if e["data"].get("kind") == "supervisor_check"]
    assert len(exported) == 1 and exported[0]["actor"] == "system" and exported[0]["detail"] == message


def test_poisoned_run_blocks_replans_and_still_repairs(fresh):
    grant, maya = _grant("poisoned")
    done = _wait(start_run(grant.grant_id, maya, planner="scripted").run_id)
    assert done.status is RunStatus.SUCCEEDED, done.outcome_summary
    assert done.replans_used == 2
    assert "ArmorIQ (simulated offline policy) blocked restore_access_grant" in done.outcome_summary
    assert "grant scope blocked prepare_repair_manifest" in done.outcome_summary
    assert mutators.count_entries("restore_access_grant", run_id=done.run_id) == 0
    assert _types(done.run_id).count("replan") == 2


def test_stale_scenario_partially_succeeds(fresh):
    grant, maya = _grant("stale")
    done = _wait(start_run(grant.grant_id, maya, planner="scripted").run_id)
    assert done.status is RunStatus.PARTIALLY_SUCCEEDED, done.outcome_summary
    types = _types(done.run_id)
    assert "external.change" in types and types.count("execution.committed") == 1
    assert "O-2042" in done.outcome_summary and "hold" in done.outcome_summary.lower()


def test_review_scenario_waits_for_second_reviewer_then_commits(fresh):
    grant, maya = _grant("review")
    run = start_run(grant.grant_id, maya, planner="scripted")
    _wait(
        run.run_id,
        until=lambda r: r.status is RunStatus.AWAITING_APPROVAL or r.status in TERMINAL_RUN_STATUSES,
    )
    pending = approvals.list_for_tenant("atlas", "pending")
    assert pending, "an approval must be requested for the high-value order"
    approvals.decide(pending[0].approval_id, get_identity("dev"), "approve", "looks right")
    done = _wait(run.run_id)
    assert done.status is RunStatus.SUCCEEDED, done.outcome_summary
    assert "O-2046" in done.outcome_summary


def test_review_rejection_changes_nothing(fresh):
    grant, maya = _grant("review")
    run = start_run(grant.grant_id, maya, planner="scripted")
    _wait(
        run.run_id,
        until=lambda r: r.status is RunStatus.AWAITING_APPROVAL or r.status in TERMINAL_RUN_STATUSES,
    )
    pending = approvals.list_for_tenant("atlas", "pending")
    approvals.decide(pending[0].approval_id, get_identity("dev"), "reject", "not today")
    done = _wait(run.run_id)
    assert done.status is RunStatus.BLOCKED, done.outcome_summary
    assert "No repair was committed" in done.outcome_summary


IDEMPOTENCY_PROBES = {"duplicate_apply", "key_reuse_different_payload"}


def _run_boundary():
    grant, maya = _grant("boundary")
    run = start_run(
        grant.grant_id, maya, planner="llm"
    )  # the boundary scenario ignores the request: always the harness
    assert run.planner == "harness" and run.planner_kind == "harness"
    return _wait(run.run_id)


def test_boundary_harness_records_probes_and_zero_forbidden_effects(fresh):
    done = _run_boundary()
    probes = done.metadata["probes"]
    assert len(probes) >= 11
    core = [p for p in probes if p["probe_id"] not in IDEMPOTENCY_PROBES]
    assert all(p["passed"] for p in core), [p for p in core if not p["passed"]]
    assert mutators.count_entries("restore_access_grant", run_id=done.run_id) == 0
    assert done.metadata["protected_checks"]["violated"] == 0


def test_boundary_idempotency_probes_reach_the_executor_after_the_grant_is_exhausted(fresh):
    """Spec: a replay after the single commit returns the ORIGINAL receipt (DUPLICATE); a reused key with a
    different payload is a domain-level BLOCK. Requires dispatch not to short-circuit exhausted-grant replays."""
    done = _run_boundary()
    by_id = {p["probe_id"]: p for p in done.metadata["probes"]}
    assert by_id["duplicate_apply"]["outcome"] == "duplicate", by_id["duplicate_apply"]
    assert by_id["duplicate_apply"]["same_operation_id"] is True
    assert by_id["key_reuse_different_payload"]["actual_layer"] == "domain", by_id[
        "key_reuse_different_payload"
    ]
    assert done.status is RunStatus.SUCCEEDED, done.outcome_summary


def test_cancel_run_stops_a_run_waiting_for_approval(fresh):
    grant, maya = _grant("review")
    run = start_run(grant.grant_id, maya, planner="scripted")
    _wait(run.run_id, until=lambda r: r.status is RunStatus.AWAITING_APPROVAL)
    cancel_run(run.run_id, maya)  # cooperative: returns at once, the worker emits run.finished when it stops
    cancelled = _wait(run.run_id)
    assert cancelled.status is RunStatus.CANCELLED
    assert "cancelled" in cancelled.outcome_summary.lower()


def test_start_run_guards(fresh, monkeypatch):
    import dataclasses

    from rewindsafe.agent import planners

    real = planners.load_settings()
    blank = {"anthropic_api_key": "", "openai_api_key": "", "groq_api_key": "", "llm_provider": "auto"}
    blank = {k: v for k, v in blank.items() if hasattr(real, k)}
    blanked = real.model_copy(update=blank) if hasattr(real, "model_copy") else dataclasses.replace(real, **blank)
    monkeypatch.setattr(planners, "load_settings", lambda: blanked)  # the dev .env may hold real LLM keys
    adapter = _adapter()
    maya = get_identity("maya")
    scenario = next(s for s in adapter.scenarios() if s.scenario_id == "clean")
    draft = grants.create_draft(adapter, scenario, maya)
    with pytest.raises(ValueError, match="authorized"):
        start_run(draft.grant_id, maya)  # draft grant
    grant = grants.authorize(draft.grant_id, maya)
    with pytest.raises(PermissionError):
        start_run(grant.grant_id, get_identity("dev"))  # not the principal
    with pytest.raises(ValueError, match="No LLM key configured"):
        start_run(grant.grant_id, maya, planner="llm")  # test env has no LLM key


# ─── P2b: async plan binding, grant closing, cancel_all_active, terminal-status guard ───


def test_plan_events_in_order_with_persisted_issuance_decision(fresh):
    from rewindsafe.runtime import events as ev

    grant, maya = _grant("clean")
    run = start_run(grant.grant_id, maya, planner="scripted")
    done = _wait(run.run_id)
    evs = ev.list_events(done.run_id, limit=2000)
    types = [e.type for e in evs]
    assert types.index("run.created") < types.index("plan.bound")
    if "plan.requested" in ev.EVENT_TYPES:
        assert types.index("plan.requested") < types.index("plan.bound")
    bound = next(e for e in evs if e.type == "plan.bound")
    assert bound.data["steps"] and "latency_ms" in bound.data and "matched_policies" in bound.data
    issuance = [
        e
        for e in evs
        if e.type == "decision"
        and e.decision is not None
        and e.decision.outcome.value == "allow"
        and e.decision.source.value in ("armoriq.offline_simulation", "armoriq.backend.token_issuance")
        and e.decision.layer.value == "armoriq"
    ]
    assert issuance, "the plan issuance decision must be emitted as a decision event"
    from rewindsafe.runtime import db

    with db.connection() as conn:
        n = conn.execute(
            "SELECT count(*) AS n FROM runtime.decisions WHERE run_id = %s AND source = ANY(%s)",
            (done.run_id, ["armoriq.offline_simulation", "armoriq.backend.token_issuance"]),
        ).fetchone()["n"]
    assert n >= 1


def test_grant_is_closed_when_the_run_ends_and_cannot_be_reused(fresh):
    grant, maya = _grant("clean")
    done = _wait(start_run(grant.grant_id, maya, planner="scripted").run_id)
    assert grants.load(grant.grant_id).status.value == "exhausted"
    with pytest.raises(ValueError, match="authorized"):
        start_run(grant.grant_id, maya, planner="scripted")
    assert done.status is RunStatus.SUCCEEDED


def test_double_start_on_one_grant_is_refused(fresh):
    grant, maya = _grant("review")
    run = start_run(grant.grant_id, maya, planner="scripted")
    with pytest.raises(ValueError, match="already has a run in progress"):
        start_run(grant.grant_id, maya, planner="scripted")
    from rewindsafe.agent import loop

    assert loop.cancel_all_active("test cleanup", wait_s=10.0) >= 1
    assert get_run(run.run_id).status is RunStatus.CANCELLED


def test_cancel_all_active_closes_runs_with_the_reason_and_run_finished(fresh):
    from rewindsafe.agent import loop

    grant, maya = _grant("review")
    run = start_run(grant.grant_id, maya, planner="scripted")
    _wait(run.run_id, until=lambda r: r.status is RunStatus.AWAITING_APPROVAL)
    assert loop.cancel_all_active("Demo fixture reset", wait_s=10.0) == 1
    done = get_run(run.run_id)
    assert done.status is RunStatus.CANCELLED
    assert "Demo fixture reset" in done.outcome_summary
    assert _types(run.run_id).count("run.finished") == 1
    assert loop.cancel_all_active("again") == 0


def test_finish_run_keeps_an_already_terminal_status_and_still_emits_run_finished(fresh):
    from rewindsafe.agent import loop
    from rewindsafe.runtime import db

    grant, maya = _grant("clean")
    adapter = _adapter()
    scenario = next(s for s in adapter.scenarios() if s.scenario_id == "clean")
    run_id = loop.create_run_row(
        grant, scenario, planner_name="scripted", planner_kind="scripted", planner_label="x",
        enforcement_mode="offline", created_by="maya",
    )
    with db.transaction() as conn:
        conn.execute(
            "UPDATE runtime.runs SET status='cancelled', outcome_summary='Fixture reset', finished_at=now() "
            "WHERE run_id=%s", (run_id,),
        )
    loop._finish_run(run_id, RunStatus.BLOCKED, "late worker summary", {"k": 1}, handle=None)
    loop._finish_run(run_id, RunStatus.BLOCKED, "late worker summary", {"k": 2}, handle=None)
    run = get_run(run_id)
    assert run.status is RunStatus.CANCELLED and run.outcome_summary == "Fixture reset"
    assert run.metadata["k"] == 2
    finished = [e for e in events.list_events(run_id, limit=100) if e.type == "run.finished"]
    assert len(finished) == 1 and finished[0].data["status"] == "cancelled"


def test_replan_counted_once_per_planner_turn():
    from types import SimpleNamespace

    from rewindsafe.agent import loop
    from rewindsafe.agent.state import ToolCall
    from rewindsafe.contracts import DispatchStatus

    st = SimpleNamespace(last_outcome=SimpleNamespace(status=DispatchStatus.BLOCKED))
    h = SimpleNamespace(state=st, planner=SimpleNamespace(kind="llm"), last_replan_turn="")
    first = ToolCall("a", {}, turn_id=2, turn_first=True)
    sibling = ToolCall("b", {}, turn_id=2, turn_first=False)
    assert loop._counts_as_replan(h, first) is True
    assert loop._counts_as_replan(h, sibling) is False
    assert loop._counts_as_replan(h, ToolCall("c", {}, turn_id=2, turn_first=True)) is False  # same turn
    assert loop._counts_as_replan(h, ToolCall("d", {}, turn_id=3, turn_first=True)) is True


def test_guarantee_breach_forces_failed_status():
    from rewindsafe.agent.loop import apply_guarantee

    assert apply_guarantee(RunStatus.SUCCEEDED, cancelled=False, violated=1, prohibited=0) == (RunStatus.FAILED, True)
    assert apply_guarantee(RunStatus.PARTIALLY_SUCCEEDED, cancelled=False, violated=0, prohibited=2) == (
        RunStatus.FAILED,
        True,
    )
    assert apply_guarantee(RunStatus.SUCCEEDED, cancelled=False, violated=0, prohibited=0) == (
        RunStatus.SUCCEEDED,
        False,
    )
    assert apply_guarantee(RunStatus.CANCELLED, cancelled=True, violated=1, prohibited=0)[0] is RunStatus.CANCELLED


def test_terminal_check_observation_remains_historical_when_adapter_state_changes(fresh, monkeypatch):
    grant, operator = _grant("clean")
    done = _wait(start_run(grant.grant_id, operator, planner="scripted").run_id)
    finish = next(event for event in events.list_events(done.run_id, limit=2000) if event.type == "run.finished")
    recorded = finish.data["protected_checks"]
    assert recorded and any(check["status"] == "preserved" for check in recorded)
    assert recorded == done.metadata["protected_check_details"]
    assert finish.data["protected_check_observation"]["source"] == "rewindsafe.end_of_run"
    monkeypatch.setattr(_adapter(), "protected_checks", lambda tenant: [])
    assert _adapter().protected_checks(grant.tenant_id) == []
    reread = next(event for event in events.list_events(done.run_id, limit=2000) if event.type == "run.finished")
    assert reread.data["protected_checks"] == recorded
