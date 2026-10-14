"""Agent run lifecycle (architecture.md section 6).

``start_run`` creates the run, binds the ArmorIQ plan *from the grant* (never from
the model), and starts a worker thread. The worker loops ``planner.next`` ->
``dispatch`` until the planner finishes or a limit is hit, then writes a terminal
status and a plain-English outcome summary. Every exception is caught: a run
ends ``failed`` with a message, the server never crashes.
"""

from __future__ import annotations

import inspect
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Jsonb

from rewindsafe.agent.planners import Planner, load_settings, select_planner
from rewindsafe.agent.state import (
    Action,
    AgentState,
    Finish,
    Note,
    PlannerError,
    ToolCall,
    build_outcome_summary,
    decisive_decision,
    layer_label,
    terminal_status,
    truncate,
)
from rewindsafe.contracts import (
    TERMINAL_RUN_STATUSES,
    Actor,
    DispatchOutcome,
    DispatchStatus,
    ExternalEvent,
    GrantStatus,
    Identity,
    PlanBinding,
    Run,
    RunStatus,
    ScenarioSpec,
)
from rewindsafe.runtime import canonical, db, events, grants
from rewindsafe.runtime.adapter import WorkflowAdapter, get_adapter

log = logging.getLogger("rewindsafe.agent.loop")

MAX_NOTES_IN_A_ROW = 30
CANCEL_JOIN_SECONDS = 1.0  # cancel is cooperative: the worker emits run.finished when it stops
_TERMINAL_VALUES = sorted(s.value for s in TERMINAL_RUN_STATUSES)


# ─── Registry of live runs (in-process) ────────────────────────────────────


@dataclass
class _Handle:
    run_id: str
    grant_id: str
    planner: Planner
    state: AgentState
    rc: Any  # rewindsafe.runtime.dispatch.RunContext
    adapter: WorkflowAdapter
    scenario: ScenarioSpec
    gateway: Any
    cancel: threading.Event
    thread: threading.Thread | None = None
    fired: dict[int, bool] = field(default_factory=dict)
    tool_successes: dict[str, int] = field(default_factory=dict)
    cancel_reason: str = ""
    last_replan_turn: str = ""
    usage_recorded: dict[str, int] = field(default_factory=dict)


_RUNS: dict[str, _Handle] = {}
_STARTING: set[str] = set()  # grants whose run is being created (closes the double-click race)
_LOCK = threading.Lock()


# ─── Small utilities ───────────────────────────────────────────────────────


def _scrub(text: str) -> str:
    """Never let a key/token reach an event, a summary or a log line."""
    out = canonical.redact_text(str(text))
    try:
        s = load_settings()
        for secret in (
            getattr(s, "anthropic_api_key", ""),
            getattr(s, "openai_api_key", ""),
            getattr(s, "groq_api_key", ""),
            getattr(s, "armoriq_api_key", ""),
        ):
            if secret and len(secret) >= 8:
                out = out.replace(secret, "[redacted]")
    except Exception:
        log.debug("could not load settings while scrubbing", exc_info=True)
    return out


def _jsonb(obj: Any) -> Jsonb:
    return Jsonb(json.loads(json.dumps(obj, default=str)))


def _resolve_adapter(workflow: str) -> WorkflowAdapter:
    try:
        return get_adapter(workflow)
    except KeyError:
        try:  # the workflow package registers its adapter on import
            import importlib

            importlib.import_module("rewindsafe.workflows.rewindsafe.adapter")
        except ImportError:
            pass
        return get_adapter(workflow)


def _row_to_run(row: dict[str, Any]) -> Run:
    return Run.model_validate(row)


_RUN_COLUMNS = (
    "run_id, grant_id, scenario_id, workflow, planner, planner_kind, enforcement_mode, status, outcome_summary, "
    "steps_used, replans_used, plan, fixture_generation, created_by, created_at, updated_at, finished_at, metadata"
)


def get_run(run_id: str) -> Run:
    with db.connection() as conn:
        row = conn.execute(f"SELECT {_RUN_COLUMNS} FROM runtime.runs WHERE run_id = %s", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"run {run_id!r} not found")
    return _row_to_run(row)


def list_runs(limit: int = 30) -> list[Run]:
    with db.connection() as conn:
        rows = conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM runtime.runs ORDER BY created_at DESC LIMIT %s", (int(limit),)
        ).fetchall()
    return [_row_to_run(r) for r in rows]


def _set_status(run_id: str, status: RunStatus, *, summary: str | None = None) -> str | None:
    """Move a run to ``status``; emits ``run.status`` on change. Terminal states are final."""
    terminal = status in TERMINAL_RUN_STATUSES
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT status FROM runtime.runs WHERE run_id = %s FOR UPDATE", (run_id,)
        ).fetchone()
        if row is None:
            return None
        previous = row["status"]
        if previous in _TERMINAL_VALUES and previous != status.value:
            return None
        if previous == status.value and summary is None:
            return previous
        conn.execute(
            "UPDATE runtime.runs SET status = %s, updated_at = now(), "
            "outcome_summary = COALESCE(%s, outcome_summary), "
            "finished_at = CASE WHEN %s THEN now() ELSE finished_at END WHERE run_id = %s",
            (status.value, summary, terminal, run_id),
        )
    if previous != status.value:
        events.emit(
            run_id,
            "run.status",
            Actor.SYSTEM,
            f"Run is now {status.value.replace('_', ' ')}",
            data={"status": status.value, "previous": previous},
        )
    return previous


def _persist_progress(h: _Handle) -> None:
    st = h.state
    try:
        with db.transaction() as conn:
            conn.execute(
                "UPDATE runtime.runs SET steps_used = %s, replans_used = %s, metadata = %s, updated_at = now() "
                "WHERE run_id = %s",
                (h.rc.step_index, st.replans_used, _jsonb(st.metadata), h.run_id),
            )
    except Exception:
        log.exception("could not persist run progress for %s", h.run_id)


# ─── Public API ────────────────────────────────────────────────────────────


def active_run_for_grant(grant_id: str) -> str | None:
    """run_id of a non-terminal run on this grant (this process or another one), else None."""
    with _LOCK:
        for h in _RUNS.values():
            if h.grant_id == grant_id and h.thread and h.thread.is_alive():
                return h.run_id
    with db.connection() as conn:
        row = conn.execute(
            "SELECT run_id FROM runtime.runs WHERE grant_id = %s AND status <> ALL(%s) LIMIT 1",
            (grant_id, _TERMINAL_VALUES),
        ).fetchone()
    return row["run_id"] if row else None


def create_run_row(
    grant: Any,
    scenario: ScenarioSpec,
    *,
    planner_name: str,
    planner_kind: str,
    planner_label: str,
    enforcement_mode: str,
    created_by: str,
    extra_metadata: dict[str, Any] | None = None,
) -> str:
    """Insert a ``created`` run row and emit ``run.created``. Shared by ``start_run`` and the MCP server."""
    run_id = canonical.new_id("run")
    metadata = {"planner_label": planner_label, **(extra_metadata or {})}
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO runtime.runs (run_id, grant_id, scenario_id, workflow, planner, planner_kind, "
            "enforcement_mode, status, fixture_generation, created_by, metadata) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                run_id,
                grant.grant_id,
                grant.scenario_id,
                grant.workflow,
                planner_name,
                planner_kind,
                enforcement_mode,
                RunStatus.CREATED.value,
                grant.fixture_generation,
                created_by,
                _jsonb(metadata),
            ),
        )
    events.emit(
        run_id,
        "run.created",
        Actor.SYSTEM,
        f"Run started: {scenario.title}",
        f"Planner: {planner_label}. Enforcement: {enforcement_mode}"
        + (" (simulated ArmorIQ)" if enforcement_mode == "offline" else ""),
        data={
            "scenario_id": scenario.scenario_id,
            "planner": planner_name,
            "planner_label": planner_label,
            "enforcement_mode": enforcement_mode,
        },
    )
    return run_id


def _bind_decision(gateway: Any, run_id: str, binding: PlanBinding, latency_ms: float) -> Any:
    """The persisted ARMORIQ token-issuance decision for a bound plan (never relabelled as live)."""
    d = None
    getter = getattr(gateway, "get_bind_decision", None)
    if callable(getter):
        try:
            d = getter(run_id)
        except Exception:
            log.debug("get_bind_decision failed", exc_info=True)
    if d is not None:
        return d
    from rewindsafe.contracts import DecisionSource, Outcome
    from rewindsafe.runtime.adapter import make_decision

    simulated = bool(binding.simulated)
    return make_decision(
        run_id,
        DecisionSource.ARMORIQ_SIMULATED if simulated else DecisionSource.ARMORIQ_TOKEN_ISSUANCE,
        Outcome.ALLOW,
        (
            f"Simulated ArmorIQ issued a signed plan token for {len(binding.steps)} tools (offline simulation)."
            if simulated
            else f"ArmorIQ issued a signed plan token for {len(binding.steps)} tools."
        ),
        simulated=simulated,
        latency_ms=latency_ms,
        evidence={"tools": list(binding.steps)},
    )


def bind_plan_for_run(
    run_id: str, grant: Any, adapter: WorkflowAdapter, gateway: Any, email: str, *, llm: str
) -> tuple[PlanBinding | None, str]:
    """Request + bind the signed plan from the GRANT (never from the model); emit the whole story.

    Emits ``plan.requested`` (before the slow live call), then ``plan.bound`` plus the persisted
    token-issuance decision, or ``plan.bind_failed``. Returns ``(binding, error)``.
    """
    simulated = gateway.mode == "offline"
    tool_calls = adapter.plan_tool_calls(grant)
    if "plan.requested" in events.EVENT_TYPES:
        events.emit(
            run_id,
            "plan.requested",
            Actor.ARMORIQ,
            "Requesting a signed intent plan from ArmorIQ"
            if not simulated
            else "Requesting a signed intent plan (simulated ArmorIQ, offline mode)",
            f"The plan is derived from the human-reviewed grant and covers {len(tool_calls)} tools; "
            "nothing the agent says can widen it.",
            data={"tools": [str(tc.get("name")) for tc in tool_calls], "llm": llm, "simulated": simulated},
        )
    t0 = time.perf_counter()
    binding: PlanBinding | None = None
    decision = None
    error = ""
    try:
        with_decision = getattr(gateway, "bind_plan_with_decision", None)
        if callable(with_decision):
            res = _call_supported(
                with_decision, run_id=run_id, grant=grant, tool_calls=tool_calls, user_email=email, llm=llm
            )
            binding, decision = res if isinstance(res, tuple) else (res, None)
        else:
            binding = _call_supported(
                gateway.bind_plan,
                run_id=run_id,
                grant=grant,
                tool_calls=tool_calls,
                user_email=email,
                llm=llm,
            )
        error = binding.error or ""
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {truncate(_scrub(str(exc)), 240)}"
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if error or binding is None:
        events.emit(
            run_id,
            "plan.bind_failed",
            Actor.ARMORIQ,
            "ArmorIQ plan could not be bound",
            _scrub(error),
            data={
                "error": _scrub(error),
                "source": "armoriq.backend.token_issuance",
                "latency_ms": round(elapsed_ms, 1),
            },
        )
        if decision is not None:
            try:
                from rewindsafe.runtime.dispatch import record_decision

                record_decision(decision, tool="plan", emit=True)
            except Exception:
                log.debug("could not record the failed issuance decision", exc_info=True)
        return None, error or "plan binding returned nothing"

    latency_ms = getattr(binding, "latency_ms", None) or elapsed_ms
    matched = list(getattr(binding, "matched_policies", None) or [])
    with db.transaction() as conn:
        conn.execute(
            "UPDATE runtime.runs SET plan = %s WHERE run_id = %s",
            (_jsonb(binding.model_dump(mode="json")), run_id),
        )
    short_hash = (binding.plan_hash or binding.plan_id or "")[:12]
    note = ""
    plan_note = getattr(adapter, "plan_note", None)
    if callable(plan_note):
        try:
            note = str(plan_note(grant) or "")
        except Exception:
            log.debug("adapter.plan_note failed", exc_info=True)
    lead = (
        "Simulated ArmorIQ plan created (offline mode)"
        if binding.simulated
        else "ArmorIQ signed the recovery plan"
    )
    events.emit(
        run_id,
        "plan.bound",
        Actor.ARMORIQ,
        lead,
        f"Plan hash {short_hash}..., {'simulated' if binding.simulated else 'signed'} in "
        f"{latency_ms / 1000:.1f} s, covers {len(binding.steps)} tools: {', '.join(binding.steps)}. "
        "Tools outside the plan cannot be called." + (f" {note}" if note else ""),
        data={
            "plan": binding.model_dump(mode="json"),
            "latency_ms": round(float(latency_ms), 1),
            "matched_policies": matched,
            "steps": list(binding.steps),
        },
    )
    d = decision if decision is not None else _bind_decision(gateway, run_id, binding, float(latency_ms))
    try:
        from rewindsafe.runtime.dispatch import record_decision

        record_decision(d, tool="plan", emit=False)
        events.emit(
            run_id,
            "decision",
            Actor.ARMORIQ,
            "Simulated ArmorIQ issued a signed plan token"
            if d.simulated
            else "ArmorIQ issued a signed plan token",
            d.reason,
            decision=d,
        )
    except Exception:
        log.exception("could not record the plan issuance decision for %s", run_id)
    return binding, ""


def start_run(grant_id: str, identity: Identity, *, planner: str = "auto") -> Run:
    """Create a run for an ACTIVE grant and start the worker; returns IMMEDIATELY.

    The slow live plan binding (about 5 s) happens in the worker so the workspace can open on a
    live timeline (``plan.requested`` -> ``plan.bound``).
    """
    from rewindsafe.runtime.armoriq_gateway import get_gateway
    from rewindsafe.runtime.dispatch import RunContext

    grant = grants.load(grant_id)
    if identity.role != "operator" or grant.principal != identity.identity_id:
        raise PermissionError("Only the operator who authorized this grant can start a run on it.")
    if grant.status is not GrantStatus.ACTIVE:
        raise ValueError(
            f"The grant must be authorized (active) before a run can start; it is {grant.status.value}."
        )
    blocked = grants.lifecycle_check(grant, grants.current_generation())
    if blocked is not None:
        raise ValueError(blocked.reason)
    with _LOCK:
        if grant_id in _STARTING or any(
            h.grant_id == grant_id and h.thread and h.thread.is_alive() for h in _RUNS.values()
        ):
            raise ValueError("This grant already has a run in progress.")
        _STARTING.add(grant_id)
    try:
        if active_run_for_grant(grant_id):
            raise ValueError("This grant already has a run in progress.")
        adapter = _resolve_adapter(grant.workflow)
        scenario = next((s for s in adapter.scenarios() if s.scenario_id == grant.scenario_id), None)
        if scenario is None:
            raise ValueError(f"Scenario {grant.scenario_id!r} is not known to workflow {grant.workflow!r}.")
        tool_specs = adapter.tool_specs()
        chosen = select_planner(planner, scenario, tool_specs)  # may raise PlannerConfigError (a ValueError)
        gateway = get_gateway()
        label = getattr(chosen, "label", chosen.name)
        briefing_meta: dict[str, Any] = {}
        if chosen.kind == "llm":
            from rewindsafe.agent.prompts import BRIEFING_LABELS, default_briefing

            briefing = default_briefing(scenario.scenario_id)
            briefing_meta = {"agent_briefing": briefing, "agent_briefing_label": BRIEFING_LABELS[briefing]}
        run_id = create_run_row(
            grant,
            scenario,
            planner_name=chosen.name,
            planner_kind=chosen.kind,
            planner_label=label,
            enforcement_mode=gateway.mode,
            created_by=identity.identity_id,
            extra_metadata=briefing_meta,
        )
        cancel = threading.Event()
        if hasattr(chosen, "should_cancel"):
            chosen.should_cancel = cancel.is_set
        state = AgentState(
            run_id=run_id,
            grant=grant,
            scenario=scenario,
            tool_specs=tool_specs,
            max_steps=grant.limits.max_steps,
            max_replans=grant.limits.max_replans,
            cancel=cancel,
        )
        state.metadata["planner_label"] = label
        state.metadata.update(briefing_meta)
        if hasattr(chosen, "on_wait"):
            chosen.on_wait = lambda secs, why, _rid=run_id: events.emit(
                _rid,
                "agent.note",
                Actor.SYSTEM,
                f"Pausing {secs:.0f} s for the LLM provider's rate limit",
                why,
                data={"rate_limit_wait_s": round(secs, 1)},
            )
        rc = RunContext(
            run_id=run_id,
            grant=grant,
            identity=identity,
            adapter=adapter,
            gateway=gateway,
            scenario=scenario,
            cancel=cancel,
        )
        handle = _Handle(run_id, grant.grant_id, chosen, state, rc, adapter, scenario, gateway, cancel)
        thread = threading.Thread(
            target=_worker, args=(handle,), name=f"rewindsafe-run-{run_id}", daemon=True
        )
        handle.thread = thread
        with _LOCK:
            _RUNS[run_id] = handle
        _set_status(run_id, RunStatus.PLANNING)
        thread.start()
    finally:
        with _LOCK:
            _STARTING.discard(grant_id)
    return get_run(run_id)


def cancel_run(run_id: str, identity: Identity) -> Run:
    """Request cancellation. The worker stops at the next step boundary (or immediately if waiting for approval)."""
    run = get_run(run_id)
    grant = grants.load(run.grant_id)
    if identity.role != "operator" or identity.tenant_id != grant.tenant_id:
        raise PermissionError("Only an operator of this tenant can cancel a run.")
    if run.status in TERMINAL_RUN_STATUSES:
        return run
    with _LOCK:
        handle = _RUNS.get(run_id)
    if handle is not None and handle.thread is not None and handle.thread.is_alive():
        handle.cancel_reason = handle.cancel_reason or f"cancelled by {identity.name}"
        handle.cancel.set()
        events.emit(
            run_id,
            "agent.note",
            Actor.OPERATOR,
            f"{identity.name} requested cancellation",
            "The run stops before its next action.",
        )
        handle.thread.join(CANCEL_JOIN_SECONDS)  # the worker emits run.finished when it actually stops
        return get_run(run_id)
    # No live worker (e.g. the server restarted): close the run out directly.
    _finish_run(
        run_id,
        RunStatus.CANCELLED,
        "The run was cancelled before it finished; no worker was active.",
        {},
        handle=None,
    )
    return get_run(run_id)


def cancel_all_active(reason: str, wait_s: float = 5.0) -> int:
    """Stop every live worker thread and close out non-terminal runs as ``cancelled`` with ``reason``.

    Called before fixture resets / the positive control / the verification suite so no worker keeps
    dispatching against a fixture that is about to change. Returns the number of runs cancelled.
    """
    with _LOCK:
        live = [h for h in _RUNS.values() if h.thread is not None and h.thread.is_alive()]
    for h in live:
        h.cancel_reason = reason
        h.cancel.set()
        try:
            events.emit(
                h.run_id,
                "agent.note",
                Actor.SYSTEM,
                f"Run stopped: {reason}",
                "The run stops before its next action.",
            )
        except Exception:
            log.debug("could not emit the cancel note for %s", h.run_id, exc_info=True)
    deadline = time.monotonic() + max(0.0, wait_s)
    for h in live:
        if h.thread is not None and h.thread is not threading.current_thread():
            h.thread.join(max(0.0, deadline - time.monotonic()))
    live_ids = {h.run_id for h in live}
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT run_id FROM runtime.runs WHERE status <> ALL(%s)", (_TERMINAL_VALUES,)
        ).fetchall()
    n = len(live_ids)
    for r in rows:
        rid = r["run_id"]
        if rid in live_ids:
            continue
        with _LOCK:
            h = _RUNS.get(rid)
        if h is not None and h.thread and h.thread.is_alive():
            continue
        _finish_run(rid, RunStatus.CANCELLED, f"The run was cancelled: {reason}.", {}, handle=None)
        n += 1
    return n


def recover_orphaned_runs() -> int:
    """At startup: mark runs that were mid-flight when the process died as failed. Returns the count."""
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT run_id FROM runtime.runs WHERE status <> ALL(%s)", (_TERMINAL_VALUES,)
        ).fetchall()
    n = 0
    for r in rows:
        with _LOCK:
            h = _RUNS.get(r["run_id"])
        if h is None or not (h.thread and h.thread.is_alive()):
            _finish_run(
                r["run_id"],
                RunStatus.FAILED,
                "The server restarted while this run was in progress.",
                {},
                handle=None,
            )
            n += 1
    return n


# ─── Worker ────────────────────────────────────────────────────────────────


def _close_gateway_run(gateway: Any, run_id: str) -> None:
    """Close the ArmorIQ plan session; live mode completes the plan (best effort) given the run's outcome."""
    try:
        outcome = get_run(run_id).status.value
    except Exception:  # noqa: BLE001
        outcome = None
    try:
        _call_supported(gateway.close_run, run_id=run_id, outcome=outcome)
    except Exception:
        log.exception("gateway.close_run failed for %s", run_id)


def _worker(h: _Handle) -> None:
    try:
        if _bind_and_check(h):
            _execute(h)
    except Exception as exc:
        log.exception("run %s crashed", h.run_id)
        try:
            _finish_run(
                h.run_id,
                RunStatus.FAILED,
                f"The agent run stopped on an unexpected error: {_scrub(type(exc).__name__ + ': ' + str(exc))}",
                h.state.metadata,
                handle=h,
            )
        except Exception:
            log.exception("could not mark run %s failed", h.run_id)
    finally:
        _close_gateway_run(h.gateway, h.run_id)
        with _LOCK:
            _RUNS.pop(h.run_id, None)


def _bind_and_check(h: _Handle) -> bool:
    """Bind the signed plan (slow when live). Returns False when the run was ended here."""
    if h.cancel.is_set():
        _finish_run(
            h.run_id,
            RunStatus.CANCELLED,
            f"The run was cancelled before it started: {h.cancel_reason or 'cancelled by an operator'}.",
            h.state.metadata,
            handle=h,
        )
        return False
    settings = load_settings()
    email = getattr(settings, "armoriq_user_email", "") or h.rc.identity.email
    binding, error = bind_plan_for_run(
        h.run_id, h.state.grant, h.adapter, h.gateway, email, llm=h.planner.name
    )
    if binding is None:
        _finish_run(
            h.run_id,
            RunStatus.FAILED,
            f"The signed ArmorIQ plan could not be created ({_scrub(error)}); no action was attempted.",
            {},
            handle=h,
        )
        return False
    return True


def _emit_note(h: _Handle, note: Note | str) -> None:
    note = Note(note) if isinstance(note, str) else note
    text = note.text
    actor = Actor.HARNESS if h.planner.kind == "harness" and note.actor is Actor.AGENT else note.actor
    short = truncate(text, 110)
    events.emit(
        h.run_id,
        "agent.note",
        actor,
        short,
        text if note.kind == "supervisor_check" or short != " ".join(text.split()) else "",
        data={"kind": note.kind},
    )


def _execute(h: _Handle) -> None:
    st, rc, planner = h.state, h.rc, h.planner
    failure: str | None = None
    stop_note = ""
    notes_in_a_row = 0
    try:
        while True:
            if h.cancel.is_set():
                break
            if rc.step_index >= st.max_steps:
                stop_note = f"Stopped at the step limit ({st.max_steps} tool calls)."
                break
            step = planner.next(st)
            if isinstance(step, Note):
                notes_in_a_row += 1
                if notes_in_a_row > MAX_NOTES_IN_A_ROW:
                    failure = "The planner produced no actions."
                    break
                _emit_note(h, step)
                continue
            if isinstance(step, Finish):
                _emit_note(h, step.summary)
                st.metadata["agent_summary"] = step.summary
                break
            if isinstance(step, Action):
                step.run(rc, st)
                _persist_progress(h)
                continue
            assert isinstance(step, ToolCall)
            notes_in_a_row = 0
            if _counts_as_replan(h, step):
                st.replans_used += 1
                if st.replans_used > st.max_replans:
                    stop_note = (
                        f"Stopped after {st.max_replans} replans without a way forward inside the grant."
                    )
                    break
                prev = st.last_outcome
                assert prev is not None and st.last_call is not None
                events.emit(
                    h.run_id,
                    "replan",
                    Actor.AGENT,
                    f"Replanning after {st.last_call.tool} was {prev.status.value.replace('_', ' ')}",
                    _replan_reason(st.last_call, prev),
                    data={"reason": _replan_reason(st.last_call, prev), "attempt": st.replans_used},
                )
            _set_status(h.run_id, RunStatus.EXECUTING)
            outcome = _dispatch(h, step)
            st.steps_used = rc.step_index
            st.record(step, outcome)
            _after_dispatch(h, step, outcome)
            _persist_progress(h)
    except PlannerError as exc:
        failure = f"The agent could not continue: {_scrub(str(exc))}"
    except Exception as exc:
        log.exception("run %s failed", h.run_id)
        failure = f"The agent run hit an unexpected error: {_scrub(type(exc).__name__ + ': ' + str(exc))}"

    cancelled = h.cancel.is_set()
    protected = _protected_summary(h)
    violated = int((protected or {}).get("violated", 0))
    try:
        from rewindsafe.runtime import mutators

        prohibited = int(mutators.count_entries("restore_access_grant", run_id=h.run_id))
    except Exception:
        log.exception("could not count prohibited handler entries for %s", h.run_id)
        prohibited = 0
    status = _call_supported(
        terminal_status,
        history=st.history,
        granted_orders=st.granted_orders,
        cancelled=cancelled,
        failure=failure,
        violated=violated,
        prohibited_entries=prohibited,
    )
    status, breach = apply_guarantee(status, cancelled=cancelled, violated=violated, prohibited=prohibited)
    probes = st.metadata.get("probes") if planner.kind == "harness" else None
    summary = build_outcome_summary(
        st.history, st.grant, status, note=failure or stop_note, protected=protected, probes=probes
    )
    if breach:
        summary = "GUARANTEE VIOLATED: " + summary
    if cancelled and h.cancel_reason:
        summary = summary.replace(
            "The run was cancelled by an operator.", f"The run was cancelled: {h.cancel_reason}."
        )
    _record_usage(h)
    usage = getattr(h.planner, "usage", None)
    if usage:
        # Preserve counters and redacted provider diagnostics even when the first model
        # request fails before a dispatcher call can persist its usual usage snapshot.
        st.metadata["token_usage"] = dict(usage)
    st.metadata["stop_reason"] = failure or stop_note or ("cancelled" if cancelled else "finished")
    _finish_run(h.run_id, status, summary, st.metadata, handle=h)


def apply_guarantee(
    status: RunStatus, *, cancelled: bool, violated: int, prohibited: int
) -> tuple[RunStatus, bool]:
    """The headline status is never green when the core guarantee broke (VIOLATED check / handler entry)."""
    breach = bool((violated or prohibited) and not cancelled)
    return (RunStatus.FAILED if breach else status), breach


def _counts_as_replan(h: _Handle, step: ToolCall) -> bool:
    """A replan is counted at most once per planner turn (parallel sibling calls are one decision)."""
    if not _is_replan(h.state, h.planner):
        return False
    if getattr(step, "turn_first", True) is False:
        return False
    turn_id = str(getattr(step, "turn_id", "") or "")
    if turn_id:
        if turn_id == h.last_replan_turn:
            return False
        h.last_replan_turn = turn_id
    return True


def _is_replan(st: AgentState, planner: Planner) -> bool:
    if planner.kind == "harness" or st.last_outcome is None:
        return False
    from rewindsafe.agent.state import FAILURE_STATUSES

    return st.last_outcome.status in FAILURE_STATUSES


def _replan_reason(call: ToolCall, out: DispatchOutcome) -> str:
    from rewindsafe.agent.state import _plain_reason

    d = decisive_decision(out)
    why = d.reason if d else str(out.observation.get("reason", out.status.value))
    return f"{layer_label(d)} refused {call.tool}: {_plain_reason(truncate(why, 200))}"


def _dispatch(h: _Handle, step: ToolCall) -> DispatchOutcome:
    from rewindsafe.runtime.dispatch import dispatch

    return dispatch(h.rc, step.tool, step.args, rationale=truncate(step.rationale, 280), source=step.source)


def _record_usage(h: _Handle) -> None:
    """Attach LLM token usage (delta since the last call) to the ArmorIQ plan trace. Best effort."""
    usage = getattr(h.planner, "usage", None)
    record = getattr(h.gateway, "record_generation", None)
    if h.planner.kind != "llm" or not usage or not callable(record):
        return
    in_now = int(usage.get("input_tokens", 0))
    out_now = int(usage.get("output_tokens", 0))
    d_in = in_now - h.usage_recorded.get("input_tokens", 0)
    d_out = out_now - h.usage_recorded.get("output_tokens", 0)
    if d_in <= 0 and d_out <= 0:
        return
    h.usage_recorded = {"input_tokens": in_now, "output_tokens": out_now}
    model = h.planner.name.split(":", 1)[-1]
    try:
        record(h.run_id, model, max(d_in, 0), max(d_out, 0))
    except Exception:
        log.debug("gateway.record_generation failed", exc_info=True)


def _after_dispatch(h: _Handle, step: ToolCall, outcome: DispatchOutcome) -> None:
    st = h.state
    usage = getattr(h.planner, "usage", None)
    if usage:
        st.metadata["token_usage"] = dict(usage)
        _record_usage(h)
    if outcome.status is not DispatchStatus.EXECUTED:
        return
    n = h.tool_successes.get(step.tool, 0) + 1
    h.tool_successes[step.tool] = n
    for i, ev in enumerate(h.scenario.external_events):
        if not h.fired.get(i) and ev.trigger_after_tool == step.tool and ev.occurrence == n:
            h.fired[i] = True
            _fire_external_event(h, ev)


# ─── Scenario external events ──────────────────────────────────────────────


def _call_supported(fn: Any, **candidates: Any) -> Any:
    """Call ``fn`` with the candidate keyword args its signature actually accepts."""
    params = inspect.signature(fn).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(**candidates)
    return fn(**{k: v for k, v in candidates.items() if k in params})


def _fire_external_event(h: _Handle, ev: ExternalEvent) -> None:
    """Inject an out-of-band authority change through the trusted admin path (never the agent)."""
    from rewindsafe.workflows.rewindsafe import authority_admin as admin

    tenant = h.state.grant.tenant_id
    entity_type = "customer" if ev.target.startswith("C-") else "order"
    if ev.action == "place_hold":
        _call_supported(
            admin.place_hold,
            tenant_id=tenant,
            entity_type=entity_type,
            entity_id=ev.target,
            reason=ev.reason,
            placed_by=ev.actor_label,
        )
        title = f"{ev.actor_label} placed a hold on {ev.target}"
    elif ev.action == "add_tombstone":
        _call_supported(
            admin.add_tombstone,
            tenant_id=tenant,
            entity_type=entity_type,
            entity_id=ev.target,
            display_name=ev.target,
            reason=ev.reason,
            deleted_by=ev.actor_label,
        )
        title = f"{ev.actor_label} deleted {ev.target}"
    else:
        _call_supported(
            admin.revoke_access,
            tenant_id=tenant,
            grant_id=ev.target,
            reason=ev.reason,
            revoked_by=ev.actor_label,
        )
        title = f"{ev.actor_label} revoked access {ev.target}"
    events.emit(
        h.run_id,
        "external.change",
        Actor.OPERATOR,
        title,
        ev.reason,
        data={"action": ev.action, "target": ev.target, "reason": ev.reason, "actor_label": ev.actor_label},
    )
    events.emit(
        h.run_id, "state.changed", Actor.SYSTEM, "Application authority changed", data={"tenant_id": tenant}
    )


# ─── Finalization ──────────────────────────────────────────────────────────


def _protected_summary(h: _Handle) -> dict[str, int] | None:
    try:
        checks = h.adapter.protected_checks(h.state.grant.tenant_id)
    except Exception:
        log.exception("protected_checks failed for %s", h.run_id)
        return None
    counts = {"total": len(checks), "violated": 0, "preserved": 0, "repaired": 0, "pending": 0}
    for c in checks:
        counts[c.status.value] = counts.get(c.status.value, 0) + 1
    h.state.metadata["protected_checks"] = counts
    # Preserve the exact observation used by the terminal safety decision.
    # Current adapter state must not be substituted for historical run evidence.
    h.state.metadata["protected_check_details"] = [c.model_dump(mode="json") for c in checks]
    h.state.metadata["protected_check_observation"] = {
        "source": "rewindsafe.end_of_run",
        "observed_at": canonical.utcnow().isoformat(),
        "scope": "adapter tenant state observed at run end",
    }
    return counts


def _finish_run(
    run_id: str, status: RunStatus, summary: str, metadata: dict[str, Any], *, handle: _Handle | None
) -> None:
    """Write the terminal status exactly once.

    If the run is already terminal (e.g. a fixture reset cancelled it in SQL while the worker was
    running), only metadata is merged: the stored status/summary are authoritative, and the closing
    ``run.finished`` event still goes out (once) so SSE streams end.
    """
    summary = _scrub(summary)
    prior_status: str | None = None
    prior_summary = ""
    grant_id: str | None = None
    try:
        with db.connection() as conn:
            row = conn.execute(
                "SELECT status, outcome_summary, grant_id FROM runtime.runs WHERE run_id = %s", (run_id,)
            ).fetchone()
        if row is not None:
            prior_status, prior_summary, grant_id = (
                row["status"],
                row["outcome_summary"] or "",
                row["grant_id"],
            )
    except Exception:
        log.exception("could not read run %s before finishing", run_id)
    already_terminal = prior_status in _TERMINAL_VALUES

    sets: list[str] = []
    params: list[Any] = []
    if not already_terminal:
        sets.append("outcome_summary = %s")
        params.append(summary)
    if metadata:
        sets.append("metadata = metadata || %s")
        params.append(_jsonb(metadata))
    if handle is not None:
        sets.append("steps_used = %s, replans_used = %s")
        params += [handle.rc.step_index, handle.state.replans_used]
    if sets:
        params.append(run_id)
        try:
            with db.transaction() as conn:
                conn.execute(
                    f"UPDATE runtime.runs SET {', '.join(sets)}, updated_at = now() WHERE run_id = %s", params
                )
        except Exception:
            log.exception("could not store run outcome for %s", run_id)
    metrics: dict[str, Any] = {}
    try:  # heavy reads first: once the status is terminal only two tiny event inserts remain
        from rewindsafe.runtime import receipts

        metrics = receipts.run_metrics(run_id)
    except Exception:
        log.exception("run_metrics failed for %s", run_id)

    final_status, final_summary = status.value, summary
    if already_terminal:
        final_status, final_summary = str(prior_status), prior_summary or summary
        try:
            with db.connection() as conn:
                dup = conn.execute(
                    "SELECT 1 FROM runtime.events WHERE run_id = %s AND event_type = 'run.finished' LIMIT 1",
                    (run_id,),
                ).fetchone()
        except Exception:  # noqa: BLE001
            dup = None
        if dup is not None:
            _close_grant(grant_id, final_status)
            return
    else:
        _set_status(run_id, status, summary=summary)
    finish_data = {"status": final_status, "outcome_summary": final_summary, "metrics": metrics}
    if "protected_check_details" in metadata:
        finish_data["protected_checks"] = metadata["protected_check_details"]
        finish_data["protected_check_observation"] = metadata.get("protected_check_observation", {})
    events.emit(
        run_id,
        "run.finished",
        Actor.SYSTEM,
        f"Run {final_status.replace('_', ' ')}",
        final_summary,
        data=finish_data,
    )
    _close_grant(grant_id, final_status)


def _close_grant(grant_id: str | None, status: str) -> None:
    """One grant = one run: the authority ends with the run (never raises)."""
    if not grant_id:
        return
    try:
        grants.close(grant_id, f"run {status}")
    except Exception:
        log.exception("could not close grant %s", grant_id)
