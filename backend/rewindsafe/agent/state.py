"""Shared agent-side types: planner steps, per-run agent state, and pure helpers.

Everything in this module is pure (no database, no network) so the planners and
the outcome-summary logic can be unit tested with fabricated ``DispatchOutcome``
objects. Nothing here grants authority: a ``ToolCall`` is just a *proposal* that
the dispatcher will check.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rewindsafe.contracts import (
    Actor,
    Decision,
    DispatchOutcome,
    DispatchStatus,
    Layer,
    Outcome,
    RunStatus,
    ScenarioSpec,
    TaskGrant,
    ToolSpec,
)

# ─── Planner steps ─────────────────────────────────────────────────────────


@dataclass
class ToolCall:
    """A proposal to call one tool. ``tag`` is planner-private bookkeeping."""

    tool: str
    args: dict[str, Any]
    rationale: str = ""
    source: str = "agent"  # "agent" | "boundary_harness"
    tag: str = ""
    # LLM planners: the provider tool-call id this proposal answers.
    call_id: str = ""
    # LLM planners: which model turn proposed this call, and whether it is the first call of that turn.
    # Sibling calls of one turn are never dispatched after a refusal, so only a turn's first call can be a
    # replan; the loop may use ``turn_first`` / ``turn_id`` to count replans per turn, not per call.
    turn_id: int = 0
    turn_first: bool = True


@dataclass
class Finish:
    summary: str


@dataclass
class Note:
    text: str
    actor: Actor = Actor.AGENT
    kind: str = "agent"


@dataclass
class Action:
    """A non-tool action the loop runs on the planner's behalf (boundary harness only).

    ``run(rc, state)`` receives the dispatcher's ``RunContext`` and the agent state.
    """

    name: str
    run: Callable[[Any, AgentState], None]


PlannerStep = ToolCall | Finish | Note | Action

# Outcomes after which the *next* proposal counts as a replan.
FAILURE_STATUSES = {
    DispatchStatus.BLOCKED,
    DispatchStatus.STALE,
    DispatchStatus.HELD_REJECTED,
    DispatchStatus.UNAVAILABLE,
    DispatchStatus.FAILED,
}
# Outcomes returned to an LLM as ``is_error`` tool results.
ERROR_STATUSES = FAILURE_STATUSES


@dataclass
class AgentState:
    """Everything a planner may look at. The planner never sees credentials."""

    run_id: str
    grant: TaskGrant
    scenario: ScenarioSpec
    tool_specs: list[ToolSpec]
    max_steps: int
    max_replans: int
    cancel: threading.Event = field(default_factory=threading.Event)
    steps_used: int = 0
    replans_used: int = 0
    last_call: ToolCall | None = None
    last_outcome: DispatchOutcome | None = None
    history: list[tuple[ToolCall, DispatchOutcome]] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)  # planner scratch space
    metadata: dict[str, Any] = field(default_factory=dict)  # persisted to run.metadata

    def record(self, call: ToolCall, outcome: DispatchOutcome) -> None:
        self.last_call = call
        self.last_outcome = outcome
        self.history.append((call, outcome))

    @property
    def granted_orders(self) -> list[str]:
        """Orders the grant lets the agent repair (directly or through review)."""
        ids: list[str] = []
        for key in ("order",):
            for oid in self.grant.resources.get(key, []) + self.grant.reviewable.get(key, []):
                if oid not in ids:
                    ids.append(oid)
        return ids

    @property
    def snapshot_id(self) -> str:
        return snapshot_id_for(self.grant)


def snapshot_id_for(grant: TaskGrant) -> str:
    sid = grant.source_constraints.get("snapshot_id")
    if sid:
        return str(sid)
    snaps = grant.resources.get("snapshot", [])
    return snaps[0] if snaps else ""


class PlannerError(RuntimeError):
    """The planner could not continue (model/API error, refusal, bad config)."""


class PlannerConfigError(PlannerError, ValueError):
    """Planner selection failed (e.g. 'llm' requested without an LLM key)."""


# ─── Outcome helpers ───────────────────────────────────────────────────────


def decisive_decision(outcome: DispatchOutcome) -> Decision | None:
    """The non-shadow decision that determined a denial (last one wins)."""
    found: Decision | None = None
    for d in outcome.decisions:
        if d.decisive and not d.shadow and d.outcome is not Outcome.ALLOW:
            found = d
    return found


def is_success(outcome: DispatchOutcome) -> bool:
    return outcome.status in (DispatchStatus.EXECUTED, DispatchStatus.DUPLICATE)


def layer_label(decision: Decision | None) -> str:
    """Honest, human label for who made a decision (never relabel a local check as ArmorIQ)."""
    if decision is None:
        return "RewindSafe"
    if decision.layer is Layer.ARMORIQ:
        return "ArmorIQ (simulated offline policy)" if decision.simulated else "ArmorIQ"
    return {
        Layer.GRANT: "VeerIQ grant scope",
        Layer.DOMAIN: "VeerIQ domain check",
        Layer.APPROVAL: "the approval step",
        Layer.POSTGRES: "PostgreSQL",
        Layer.RUNTIME: "the VeerIQ runtime",
    }.get(decision.layer, "RewindSafe")


def observation_text(obs: dict[str, Any], key: str, default: str = "") -> str:
    val = obs.get(key)
    return str(val) if val not in (None, "") else default


def extract_orders(observation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Pull per-order entries out of a compare/inspect observation, tolerantly.

    Accepts ``{"orders": [{order_id,...}]}`` (also ``comparisons``/``results``/``items``/
    ``rows``), a bare list, or a mapping keyed by order id.
    """
    if isinstance(observation, list):  # defensive: caller passed a list
        candidates: Any = observation
    else:
        candidates = None
        for key in ("orders", "comparisons", "results", "items", "rows"):
            val = observation.get(key)
            if isinstance(val, (list, dict)):
                candidates = val
                break
    out: dict[str, dict[str, Any]] = {}
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, dict) and item.get("order_id"):
                out[str(item["order_id"])] = item
    elif isinstance(candidates, dict):
        for k, v in candidates.items():
            if isinstance(v, dict):
                out[str(k)] = {"order_id": k, **v}
    return out


def extract_annotations(observation: dict[str, Any]) -> list[dict[str, Any]]:
    val = observation.get("annotations")
    if isinstance(val, list):
        return [a for a in val if isinstance(a, dict)]
    return []


_CONDITION_PHRASE = {
    "damaged": "damaged by the incident",
    "healthy": "already healthy",
    "changed_after_snapshot": "changed legitimately after the snapshot (left as is)",
    "deleted_tombstoned": "deleted after the snapshot (left deleted)",
    "on_hold": "under a record hold",
}


def condition_phrase(condition: str) -> str:
    return _CONDITION_PHRASE.get(condition, condition.replace("_", " "))


def manifest_ref(outcome: DispatchOutcome) -> tuple[str, str]:
    """(manifest_id, manifest_digest) taken from the prepare outcome - never invented."""
    if outcome.manifest is not None:
        return outcome.manifest.manifest_id, outcome.manifest.content_digest
    obs = outcome.observation
    return (
        str(obs.get("manifest_id") or ""),
        str(obs.get("manifest_digest") or obs.get("content_digest") or ""),
    )


def dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def join_ids(ids: list[str]) -> str:
    ids = list(ids)
    if not ids:
        return "none"
    if len(ids) == 1:
        return ids[0]
    return ", ".join(ids[:-1]) + " and " + ids[-1]


# ─── Terminal status + plain-English summary ───────────────────────────────


def committed_receipts(history: list[tuple[ToolCall, DispatchOutcome]]):
    """Receipts of mutations this run actually committed (duplicates excluded)."""
    seen: set[str] = set()
    out = []
    for call, o in history:
        r = o.receipt
        if (
            call.tool == "apply_repair_manifest"  # a receipt *fetch* is a read, not a commit
            and o.status is DispatchStatus.EXECUTED
            and r is not None
            and r.result == "committed"
            and r.operation_id not in seen
        ):
            seen.add(r.operation_id)
            out.append(r)
    return out


def repaired_orders(history: list[tuple[ToolCall, DispatchOutcome]]) -> list[str]:
    ids: list[str] = []
    for r in committed_receipts(history):
        for ch in r.changes:
            if ch.row_id not in ids:
                ids.append(ch.row_id)
    return ids


def latest_conditions(history: list[tuple[ToolCall, DispatchOutcome]]) -> dict[str, dict[str, Any]]:
    """Most recent compare_current view of each order."""
    latest: dict[str, dict[str, Any]] = {}
    for call, o in history:
        if call.tool == "compare_current" and is_success(o):
            latest.update(extract_orders(o.observation))
    return latest


def _damaged_fields(history: list[tuple[ToolCall, DispatchOutcome]]) -> dict[str, set[str]]:
    """Fields each order differed on in the FIRST compare_current that reported it (pre-repair view)."""
    first: dict[str, set[str]] = {}
    for call, o in history:
        if call.tool == "compare_current" and is_success(o):
            for oid, row in extract_orders(o.observation).items():
                diffs = row.get("differing_fields")
                if oid not in first and isinstance(diffs, list):
                    first[oid] = {str(f) for f in diffs}
    return first


def unrepaired_fields(history: list[tuple[ToolCall, DispatchOutcome]]) -> dict[str, list[str]]:
    """Per touched order, the damaged fields that no committed receipt restored."""
    restored: dict[str, set[str]] = {}
    for r in committed_receipts(history):
        for ch in r.changes:
            restored.setdefault(ch.row_id, set()).add(ch.field)
    damaged = _damaged_fields(history)
    return {
        oid: sorted(damaged.get(oid, set()) - fields)
        for oid, fields in restored.items()
        if damaged.get(oid, set()) - fields
    }


def fully_repaired_orders(history: list[tuple[ToolCall, DispatchOutcome]]) -> list[str]:
    """Orders whose every damaged field was restored by a committed receipt."""
    partial = unrepaired_fields(history)
    return [oid for oid in repaired_orders(history) if oid not in partial]


def terminal_status(
    history: list[tuple[ToolCall, DispatchOutcome]],
    granted_orders: list[str],
    *,
    cancelled: bool = False,
    failure: str | None = None,
) -> RunStatus:
    """Section 6 terminal-status rules."""
    if cancelled:
        return RunStatus.CANCELLED
    if failure:
        return RunStatus.FAILED
    commits = committed_receipts(history)
    if commits:
        # An order counts only when every damaged field came back, not merely when it was touched.
        done = set(fully_repaired_orders(history))
        return (
            RunStatus.SUCCEEDED if all(o in done for o in granted_orders) else RunStatus.PARTIALLY_SUCCEEDED
        )
    if any(o.status in FAILURE_STATUSES for _, o in history):
        return RunStatus.BLOCKED
    return RunStatus.FAILED  # finished without any effect and nothing was denied


def _reason_snippet(text: str, limit: int = 140) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_PLAIN_REASONS = (
    ("tool-not-in-plan", "it is not in the signed recovery plan."),
    ("tool_not_in_allowlist", "the organization's policy does not allow it."),
    ("no_matching_policy", "no ArmorIQ policy allows it (default deny)."),
    ("enforce-unavailable", "the enforcement service could not be reached, so it was refused (fail closed)."),
)


def _plain_reason(text: str) -> str:
    """Known enforcement codes in plain English; anything else trimmed and closed with a period."""
    raw = " ".join(str(text).split())
    for code, plain in _PLAIN_REASONS:
        if raw.startswith(code):
            return plain
    snippet = _reason_snippet(raw)
    return snippet if snippet.endswith((".", "…", "!", "?")) else snippet + "."


def build_outcome_summary(
    history: list[tuple[ToolCall, DispatchOutcome]],
    grant: TaskGrant,
    status: RunStatus,
    *,
    note: str = "",
    protected: dict[str, int] | None = None,
    probes: list[dict[str, Any]] | None = None,
) -> str:
    """Plain-English outcome for the run header and the evidence export."""
    sentences: list[str] = []
    snap = snapshot_id_for(grant)

    receipts = committed_receipts(history)
    done = repaired_orders(history)
    if receipts:
        rows = sum(len(r.changes) for r in receipts)
        sentences.append(
            f"Repaired {join_ids(done)} from approved snapshot {snap} "
            f"({rows} field{'s' if rows != 1 else ''} restored in {len(receipts)} commit"
            f"{'s' if len(receipts) != 1 else ''})."
        )
    else:
        sentences.append("No repair was committed; application data was not changed by this run.")

    granted = list(dict.fromkeys(grant.resources.get("order", []) + grant.reviewable.get("order", [])))
    missing = [o for o in granted if o not in done]
    if receipts and missing:
        conds = latest_conditions(history)
        why = []
        for oid in missing:
            c = str(conds.get(oid, {}).get("condition", ""))
            why.append(f"{oid} ({condition_phrase(c)})" if c else oid)
        sentences.append("Not repaired: " + ", ".join(why) + ".")
    partial = unrepaired_fields(history)
    if partial:
        parts = [f"{oid} ({', '.join(f.replace('_', ' ') for f in fields)} still damaged)" for oid, fields in partial.items()]
        sentences.append("Only partly repaired: " + "; ".join(parts) + ".")

    if probes is not None:
        ok = sum(1 for p in probes if p.get("passed"))
        sentences.append(
            f"Boundary harness: {ok} of {len(probes)} probes were stopped (or behaved) at the expected layer."
        )
    else:
        seen: set[tuple[str, str]] = set()
        for call, o in history:
            if o.status is DispatchStatus.BLOCKED:
                d = decisive_decision(o)
                who = layer_label(d)
                key = (call.tool, who)
                if key in seen:
                    continue
                seen.add(key)
                reason = d.reason if d else observation_text(o.observation, "reason", "outside the grant")
                sentences.append(f"{who} blocked {call.tool}: {_plain_reason(reason)}")
            elif o.status is DispatchStatus.STALE:
                sentences.append(
                    "A commit was rejected because state changed after the preview: "
                    + _reason_snippet(observation_text(o.observation, "reason", "preconditions changed"))
                )
            elif o.status is DispatchStatus.HELD_REJECTED:
                sentences.append(
                    "A reviewer did not approve the held action (rejected, timed out or expired), so nothing changed."
                )
            elif o.status is DispatchStatus.UNAVAILABLE:
                sentences.append(
                    f"Enforcement was unavailable for {call.tool}; it failed closed and nothing was executed."
                )
            elif o.status is DispatchStatus.FAILED:
                sentences.append(
                    f"{call.tool} failed: {_reason_snippet(observation_text(o.observation, 'reason', 'tool error'))}"
                )

    if protected is not None:
        total = protected.get("total", 0)
        violated = protected.get("violated", 0)
        if violated:
            sentences.append(f"WARNING: {violated} of {total} protected-state checks were violated.")
        elif total:
            sentences.append(
                f"All {total} protected-state checks held (deleted records stayed deleted, revoked access stayed "
                "revoked, later legitimate edits and other tenants were untouched)."
            )

    if note:
        sentences.append(note)
    if status is RunStatus.CANCELLED:
        sentences.append("The run was cancelled by an operator.")
    return " ".join(sentences)


# ─── Misc ──────────────────────────────────────────────────────────────────

_RE_ORDER_ID = re.compile(r"\b[A-Z]-\d{4}\b")
_RE_GRANT_ID = re.compile(r"\bAG-\d+\b")


def truncate(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
