"""The ONE checked path to effects (architecture.md 4.10).

Every tool call - from the LLM agent, the scripted agent, the boundary harness or
the MCP server - goes through :func:`dispatch`. Layers, outermost first:

    runtime registry/schema -> lifecycle -> ArmorIQ (signed plan + policy)
    -> grant scope -> domain invariants -> approval (if held / reviewable)
    -> full re-validation -> adapter.execute (sole executor; PostgreSQL privileges below)

``adapter.execute`` is only reachable at the end of that chain. After an approval
the whole admission (lifecycle, ArmorIQ, grant, domain) is run AGAIN against current
state and the freshly derived payload must equal the approved payload exactly.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Jsonb

from rewindsafe.contracts import (
    ActionProposal,
    Actor,
    ApprovalRecord,
    ApprovalStatus,
    Decision,
    DecisionSource,
    DispatchOutcome,
    DispatchStatus,
    Identity,
    Layer,
    Outcome,
    ProposalStatus,
    RunStatus,
    ScenarioSpec,
    TaskGrant,
    ToolKind,
    ToolSpec,
)
from rewindsafe.runtime import approvals, db, events, grants
from rewindsafe.runtime.adapter import (
    AdmissionResult,
    ReviewRequirement,
    ToolContext,
    ToolExecution,
    WorkflowAdapter,
    make_decision,
)
from rewindsafe.runtime.armoriq_gateway import EnforcementGateway, sdk_version
from rewindsafe.runtime.canonical import (
    canonical_json,
    digest,
    new_id,
    redact_secrets,
    redact_text,
    to_jsonable,
    utcnow,
)
from rewindsafe.runtime.identities import get_identity

log = logging.getLogger(__name__)

GUIDANCE_BLOCKED = (
    "Do not retry this action; it is outside your authority. "
    "Choose an action within the grant or report what cannot be done."
)
GUIDANCE_UNAVAILABLE = (
    "Enforcement is unavailable, so this action was refused (fail closed). "
    "Do not retry in a loop; report that enforcement could not be reached."
)
GUIDANCE_REJECTED = (
    "A reviewer did not approve this action (or it was not approved in time). "
    "Do not retry it; continue with what is within your grant and report the outcome."
)
GUIDANCE_STALE = (
    "State changed after you prepared this action, so nothing was applied. Re-inspect the current "
    "state, prepare a fresh manifest for what is still permitted, or report what cannot be done."
)

_LAYER_LABEL = {
    Layer.ARMORIQ: "ArmorIQ",
    Layer.GRANT: "Grant scope",
    Layer.DOMAIN: "Domain check",
    Layer.APPROVAL: "Approval",
    Layer.POSTGRES: "PostgreSQL",
    Layer.RUNTIME: "Runtime",
}
_ARMORIQ_SOURCES = {
    DecisionSource.ARMORIQ_PLAN_BINDING,
    DecisionSource.ARMORIQ_ENFORCE,
    DecisionSource.ARMORIQ_TOKEN_ISSUANCE,
    DecisionSource.ARMORIQ_APPROVAL,
    DecisionSource.ARMORIQ_SIMULATED,
}
_PROPOSAL_STATUS = {
    DispatchStatus.EXECUTED: ProposalStatus.EXECUTED,
    DispatchStatus.STALE: ProposalStatus.STALE,
    DispatchStatus.FAILED: ProposalStatus.FAILED,
    DispatchStatus.DUPLICATE: ProposalStatus.DUPLICATE,
    DispatchStatus.BLOCKED: ProposalStatus.BLOCKED,
}
_VALID_SOURCES = ("agent", "boundary_harness", "operator", "mcp")


@dataclass
class RunContext:
    run_id: str
    grant: TaskGrant
    identity: Identity
    adapter: WorkflowAdapter
    gateway: EnforcementGateway
    scenario: ScenarioSpec
    cancel: threading.Event
    step_index: int = 0


# ─── JSON-schema subset ───────────────────────────────────────────────────


def _type_name(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _type_ok(t: str, v: Any) -> bool:
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "null":
        return v is None
    return False


def _same(a: Any, b: Any) -> bool:
    return isinstance(a, bool) == isinstance(b, bool) and a == b


def validate_json_schema(schema: dict[str, Any], instance: Any, path: str = "$") -> list[str]:
    """Validate ``instance`` against a small JSON-schema subset; returns error strings.

    Supported: ``type`` (string or list), ``required``, ``properties``, ``items``,
    ``additionalProperties`` (``false`` or a schema), ``enum``, ``minItems``, ``maxItems``,
    ``minLength``, ``maxLength``, ``minimum``, ``maximum``. Anything else in the schema is
    ignored, so every tool schema must stick to this list (tests/unit/test_schema_limits.py).
    """
    errors: list[str] = []
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(x, instance) for x in types):
            errors.append(f"{path}: expected {' or '.join(types)}, got {_type_name(instance)}")
            return errors
    if "enum" in schema and not any(_same(instance, e) for e in schema["enum"]):
        errors.append(f"{path}: must be one of {schema['enum']}")
    if isinstance(instance, dict):
        for name in schema.get("required", []):
            if name not in instance:
                errors.append(f"{path}.{name}: required property is missing")
        props = schema.get("properties", {})
        for name, sub in props.items():
            if name in instance:
                errors.extend(validate_json_schema(sub, instance[name], f"{path}.{name}"))
        extra = schema.get("additionalProperties", True)
        for name in instance:
            if name in props:
                continue
            if extra is False:
                errors.append(f"{path}.{name}: unexpected property")
            elif isinstance(extra, dict):
                errors.extend(validate_json_schema(extra, instance[name], f"{path}.{name}"))
    elif isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: needs at most {schema['maxItems']} item(s)")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(instance):
                errors.extend(validate_json_schema(item_schema, item, f"{path}[{i}]"))
    elif isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: must be at least {schema['minLength']} character(s)")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: must be at most {schema['maxLength']} character(s)")
    elif isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: must be >= {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: must be <= {schema['maximum']}")
    return errors


# ─── persistence helpers ──────────────────────────────────────────────────


def _insert_proposal(p: ActionProposal) -> None:
    with db.autocommit_connection() as conn:
        conn.execute(
            "INSERT INTO runtime.proposals (proposal_id, run_id, step_index, tool, arguments, rationale, source, status, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                p.proposal_id,
                p.run_id,
                p.step_index,
                p.tool,
                Jsonb(p.arguments),
                p.rationale,
                p.source,
                p.status.value,
                p.created_at,
            ),
        )
        conn.execute(
            "UPDATE runtime.runs SET steps_used = GREATEST(steps_used, %s), updated_at = now() WHERE run_id = %s",
            (p.step_index + 1, p.run_id),
        )


def _set_proposal_status(proposal_id: str, status: ProposalStatus) -> None:
    with db.autocommit_connection() as conn:
        conn.execute(
            "UPDATE runtime.proposals SET status = %s WHERE proposal_id = %s", (status.value, proposal_id)
        )


def _insert_decision(d: Decision) -> None:
    with db.autocommit_connection() as conn:
        conn.execute(
            "INSERT INTO runtime.decisions (decision_id, run_id, proposal_id, layer, source, outcome, decisive, shadow, simulated, body, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                d.decision_id,
                d.run_id,
                d.proposal_id,
                d.layer.value,
                d.source.value,
                d.outcome.value,
                d.decisive,
                d.shadow,
                d.simulated,
                Jsonb(redact_secrets(d)),
                d.created_at,
            ),
        )


def _run_status(run_id: str) -> str | None:
    with db.connection() as conn:
        row = conn.execute("SELECT status FROM runtime.runs WHERE run_id = %s", (run_id,)).fetchone()
    return row["status"] if row else None


def _set_run_status(run_id: str, status: RunStatus) -> None:
    with db.autocommit_connection() as conn:
        row = conn.execute(
            "UPDATE runtime.runs r SET status = %s, updated_at = now() "
            "FROM (SELECT status FROM runtime.runs WHERE run_id = %s) old WHERE r.run_id = %s RETURNING old.status AS previous",
            (status.value, run_id, run_id),
        ).fetchone()
    previous = row["previous"] if row else None
    if previous != status.value:
        events.emit(
            run_id,
            "run.status",
            Actor.SYSTEM,
            f"Run is now {status.value.replace('_', ' ')}",
            "",
            data={"status": status.value, "previous": previous},
        )


def _event_exists_after(run_id: str, event_type: str, after_seq: int) -> bool:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM runtime.events WHERE run_id = %s AND event_type = %s AND seq > %s LIMIT 1",
            (run_id, event_type, after_seq),
        ).fetchone()
    return row is not None


# ─── copy for the timeline ────────────────────────────────────────────────


def _plan_ref(d: Decision) -> str:
    ref = None
    if d.sponsor:
        ref = d.sponsor.plan_hash or d.sponsor.plan_id
    if not ref:
        return "unknown"
    return ref.split(":", 1)[-1][:8] + "…"


def decision_copy(d: Decision, tool: str, *, recheck: bool = False) -> tuple[str, str]:
    """Plain-English ``(title, detail)`` for a decision event."""
    label = _LAYER_LABEL[d.layer]
    suffix = " (re-check after approval)" if recheck else ""
    if d.shadow:
        return (
            f"{label} would also have blocked {tool}",
            f"{d.reason} (Shadow check for attribution; the action had already been stopped.)",
        )
    if d.layer == Layer.ARMORIQ:
        who = "Simulated ArmorIQ" if d.simulated else "ArmorIQ"
        note = " Offline simulation, not sponsor enforcement." if d.simulated else ""
        if d.source == DecisionSource.ARMORIQ_TOKEN_ISSUANCE and d.outcome == Outcome.ALLOW:
            return (f"{who} issued a signed intent plan", f"{d.reason}{note}".strip())
        if d.invariant in ("org_policy_allowlist", "remint_wider_refused") and d.outcome == Outcome.BLOCK:
            return (
                f"{who} refused a wider plan",
                f"{d.reason} The extra tools were never issued authority.{note}".strip(),
            )
        if d.invariant == "plan_issued" and d.outcome == Outcome.ALLOW:
            return (f"{who} issued a signed intent plan", f"{d.reason}{note}".strip())
        if d.outcome == Outcome.BLOCK:
            if d.source == DecisionSource.ARMORIQ_PLAN_BINDING or d.invariant == "tool_not_in_signed_plan":
                return (
                    f"{who} blocked {tool}{suffix}",
                    f"Not in the signed recovery plan (plan {_plan_ref(d)}). The handler was never entered.{note}",
                )
            return f"{who} blocked {tool}{suffix}", f"{d.reason} The handler was never entered.{note}"
        if d.outcome == Outcome.ALLOW:
            return (
                f"{who} allowed {tool}{suffix}",
                f"Inside the signed recovery plan and permitted by policy.{note}",
            )
        if d.outcome == Outcome.HOLD:
            return f"{who} held {tool} for approval{suffix}", f"{d.reason}{note}"
        if d.outcome == Outcome.UNAVAILABLE:
            return (
                f"{who} unreachable: {tool} refused (fail closed){suffix}",
                f"Enforcement could not be reached, so the action was refused. This is not a policy denial. {d.reason}",
            )
    if d.outcome == Outcome.BLOCK:
        never = (
            " The handler was never entered."
            if d.decisive and d.layer in (Layer.GRANT, Layer.DOMAIN, Layer.RUNTIME, Layer.APPROVAL)
            else ""
        )
        return f"{label} blocked {tool}{suffix}", f"{d.reason}{never}"
    if d.outcome == Outcome.HOLD:
        return f"{label} holds {tool}{suffix}", d.reason
    if d.outcome == Outcome.ALLOW:
        return f"{label} allowed {tool}{suffix}", d.reason
    return f"{label} {d.outcome.value} {tool}{suffix}", d.reason


def _actor_for(d: Decision) -> Actor:
    return {
        Layer.ARMORIQ: Actor.ARMORIQ,
        Layer.POSTGRES: Actor.POSTGRES,
        Layer.APPROVAL: Actor.REVIEWER if d.invariant == "approval_rejected" else Actor.REWINDSAFE,
    }.get(d.layer, Actor.REWINDSAFE)


def record_decision(d: Decision, *, tool: str = "", emit: bool = True, recheck: bool = False) -> Decision:
    """Persist a decision (``runtime.decisions``) and emit its ``decision`` event.

    Public so other components (e.g. the boundary harness recording a ``probe_wider_plan`` result)
    use the exact same persistence and copy.
    """
    d = d.model_copy(update={"reason": redact_text(d.reason)})
    _insert_decision(d)
    if emit:
        title, detail = decision_copy(d, tool or d.evidence.get("tool", "action"), recheck=recheck)
        events.emit(d.run_id, "decision", _actor_for(d), title, detail, proposal_id=d.proposal_id, decision=d)
    return d


# ─── dispatcher ───────────────────────────────────────────────────────────


@dataclass
class _Admit:
    stop: DispatchOutcome | None = None
    hold: bool = False
    delegation_id: str | None = None
    review: ReviewRequirement | None = None
    canonical: dict[str, Any] = field(default_factory=dict)


class _Dispatcher:
    def __init__(self, rc: RunContext, proposal: ActionProposal, spec: ToolSpec | None) -> None:
        self.rc = rc
        self.p = proposal
        self.spec = spec
        self.decisions: list[Decision] = []
        self.approval: ApprovalRecord | None = None
        self.ctx: ToolContext | None = None
        self.prop_seq = 0
        self._cleared = False  # True only after every layer (and any approval) allowed
        self._synth_review = False
        self._execution_started = False
        self._sponsor_approved_id: str | None = None  # ArmorIQ delegation approved in this dispatch
        self.canonical: dict[str, Any] = {}  # server-derived args ArmorIQ was asked to check
        self._reported = False
        self._duration_ms: float | None = None

    # -- small helpers --------------------------------------------------------

    @property
    def tool(self) -> str:
        return self.p.tool

    def _record(self, d: Decision, *, recheck: bool = False) -> Decision:
        d = d.model_copy(update={"run_id": self.rc.run_id, "proposal_id": self.p.proposal_id})
        d = record_decision(d, tool=self.tool, recheck=recheck)
        self.decisions.append(d)
        return d

    def _denied(
        self,
        d: Decision,
        dstatus: DispatchStatus,
        pstatus: ProposalStatus,
        guidance: str = GUIDANCE_BLOCKED,
    ) -> DispatchOutcome:
        _set_proposal_status(self.p.proposal_id, pstatus)
        self.p = self.p.model_copy(update={"status": pstatus})
        status_word = {
            DispatchStatus.UNAVAILABLE: "unavailable",
            DispatchStatus.HELD_REJECTED: "rejected",
        }.get(dstatus, "blocked")
        obs = {
            "status": status_word,
            "blocked_by": d.source.value,
            "reason": d.reason,
            "guidance": guidance,
        }
        if d.invariant:
            obs["invariant"] = d.invariant
        self._report_blocked_attempt(d, dstatus)
        return DispatchOutcome(
            proposal=self.p,
            status=dstatus,
            decisions=self.decisions,
            observation=redact_secrets(obs),
            approval=self.approval,
        )

    def _armoriq_allowed_or_held(self) -> bool:
        return any(
            x.layer == Layer.ARMORIQ and not x.shadow and x.outcome in (Outcome.ALLOW, Outcome.HOLD)
            for x in self.decisions
        )

    def _approver(self) -> tuple[str | None, str | None]:
        """(name, email) of the reviewer who approved this action, if any."""
        rec = self.approval
        if rec is None or rec.status != ApprovalStatus.APPROVED or not rec.decided_by:
            return None, None
        try:
            who = get_identity(rec.decided_by)
        except Exception:  # noqa: BLE001
            who = None
        if who is None:
            return rec.decided_by, None
        return who.name, getattr(who, "email", None)

    def _report_blocked_attempt(self, d: Decision, dstatus: DispatchStatus) -> None:
        """Best-effort ArmorIQ audit row for an attempt that did not execute (R1-11 / R2-10).

        Covers a local plan-binding block and every block that happened AFTER ArmorIQ allowed (or held)
        the action (grant scope, domain, approval, payload change), so the ArmorIQ audit log tells the
        whole story instead of only the successes. ArmorIQ's own enforce blocks and fail-closed
        unavailability are not re-reported.
        """
        if self._reported or dstatus == DispatchStatus.UNAVAILABLE:
            return
        if d.layer == Layer.ARMORIQ and d.source != DecisionSource.ARMORIQ_PLAN_BINDING:
            if d.invariant not in ("armoriq_hold_not_cleared", "sponsor_not_approved"):
                return
        if not (d.source == DecisionSource.ARMORIQ_PLAN_BINDING or self._armoriq_allowed_or_held()):
            return
        self._reported = True
        try:
            name, email = self._approver()
            summary: dict[str, Any] = {
                "status": "blocked",
                "summary": "blocked attempt (not executed)",
                "blocked_by": d.source.value,
                "invariant": d.invariant,
                "reason": redact_text(d.reason)[:300],
                "error_message": redact_text(f"not executed: blocked by {d.source.value} ({d.invariant})")[:300],
            }
            if name:
                summary["approved_by"] = name
                summary["approved_by_email"] = email
            self.rc.gateway.report(
                self.rc.run_id,
                self.p.proposal_id,
                self.tool,
                self.canonical or self.p.arguments,
                summary,
                "failed",
            )
        except Exception:  # noqa: BLE001
            log.exception("gateway.report (blocked attempt) failed")

    def _block(
        self,
        source: DecisionSource,
        reason: str,
        invariant: str,
        *,
        evidence: dict[str, Any] | None = None,
        recheck: bool = False,
        pstatus: ProposalStatus = ProposalStatus.BLOCKED,
        dstatus: DispatchStatus = DispatchStatus.BLOCKED,
    ) -> DispatchOutcome:
        d = self._record(
            make_decision(
                self.rc.run_id,
                source,
                Outcome.BLOCK,
                reason,
                invariant=invariant,
                decisive=True,
                evidence=evidence,
            ),
            recheck=recheck,
        )
        return self._denied(d, dstatus, pstatus)

    @staticmethod
    def _adapter_decision_ok(d: Decision) -> bool:
        # A local check must never be labeled as ArmorIQ.
        return d.layer != Layer.ARMORIQ and d.source not in _ARMORIQ_SOURCES

    # -- the pipeline ----------------------------------------------------------

    def run(self) -> DispatchOutcome:
        rc = self.rc
        # 2. runtime layer: registry, schema, cancellation, step budget
        if self.spec is None:
            return self._block(
                DecisionSource.TOOL_REGISTRY,
                f"'{self.tool}' is not a tool of this workflow.",
                "unknown_tool",
            )
        problems = validate_json_schema(self.spec.input_schema, self.p.arguments)
        if problems:
            return self._block(
                DecisionSource.TOOL_REGISTRY,
                "Arguments do not match the tool schema: " + "; ".join(problems[:5]),
                "schema_violation",
                evidence={"errors": problems[:10]},
            )
        if rc.cancel.is_set():
            return self._block(DecisionSource.LIFECYCLE, "The run was cancelled.", "run_cancelled")
        if self.p.step_index >= rc.grant.limits.max_steps:
            return self._block(
                DecisionSource.LIFECYCLE,
                f"The run used its step budget ({rc.grant.limits.max_steps} proposals).",
                "step_budget",
            )

        # 3-7. lifecycle, canonicalize, ArmorIQ, grant, domain
        admit = self._admit(recheck=False)
        if admit.stop:
            return admit.stop

        # 8. approval (ArmorIQ HOLD and/or adapter review)
        if admit.hold or admit.review:
            stop = self._approval(admit)
            if stop:
                return stop
        return self._execute()

    # steps 3-7 -------------------------------------------------------------

    @staticmethod
    def _is_receipted_replay(grant: TaskGrant, tool: str, args: dict[str, Any]) -> bool:
        """True for an apply whose (grant, idempotency key) already has a receipt."""
        key = args.get("idempotency_key") if isinstance(args, dict) else None
        if tool != "apply_repair_manifest" or not isinstance(key, str) or not key:
            return False
        try:
            with db.connection() as conn:
                row = conn.execute(
                    "SELECT 1 FROM runtime.receipts WHERE grant_id = %s AND idempotency_key = %s",
                    (grant.grant_id, key),
                ).fetchone()
                conn.rollback()
            return row is not None
        except Exception:  # noqa: BLE001 - on doubt keep the lifecycle block
            return False

    def _admit(self, *, recheck: bool) -> _Admit:
        rc, tool, args = self.rc, self.tool, self.p.arguments
        self._cleared = False
        spec = self.spec
        assert spec is not None
        mutator = spec.mutator or spec.kind in (ToolKind.MUTATE, ToolKind.ADMIN)

        # 3. lifecycle (always against the freshly loaded grant)
        try:
            grant = grants.load(rc.grant.grant_id)
        except grants.GrantError as exc:
            return _Admit(
                stop=self._block(
                    DecisionSource.LIFECYCLE,
                    f"The grant could not be loaded: {exc}",
                    "grant_inactive",
                    recheck=recheck,
                )
            )
        rc.grant = grant
        life = grants.lifecycle_check(
            grant,
            grants.current_generation(),
            run_id=rc.run_id,
            proposal_id=self.p.proposal_id,
            # An exhausted budget is enforced by the executor under the grant lock, *after* its
            # idempotency check, so a replay of a used key returns the original receipt and a
            # reused key with a different payload is rejected as such (architecture 5.5).
            tool_is_mutator=mutator and not self._is_receipted_replay(grant, tool, args),
        )
        if life is not None:
            d = self._record(life, recheck=recheck)
            return _Admit(stop=self._denied(d, DispatchStatus.BLOCKED, ProposalStatus.BLOCKED))
        ctx = ToolContext(
            run_id=rc.run_id,
            proposal=self.p,
            grant=grant,
            identity=rc.identity,
            scenario=rc.scenario,
            enforcement_mode=rc.gateway.mode,
            sdk_version=sdk_version() if rc.gateway.mode == "live" else None,
            approval=None,
        )
        self.ctx = ctx

        # 4. canonical, server-derived arguments for ArmorIQ
        canon_error: str | None = None
        try:
            canonical = rc.adapter.canonicalize(ctx, tool, args)
        except Exception as exc:  # noqa: BLE001 - a canonicalization failure is a refusal, not a crash
            canon_error = f"{type(exc).__name__}: {exc}"
            canonical = dict(args)
            log.info("canonicalize failed for %s: %s", tool, canon_error)
        self.canonical = canonical

        # 5. ArmorIQ
        try:
            ad = rc.gateway.check(rc.run_id, self.p.proposal_id, tool, canonical)
            if ad.layer != Layer.ARMORIQ:
                raise ValueError("gateway returned a non-ArmorIQ decision")
        except Exception as exc:  # noqa: BLE001 - fail closed
            ad = make_decision(
                rc.run_id,
                DecisionSource.ARMORIQ_ENFORCE,
                Outcome.UNAVAILABLE,
                f"The enforcement gateway failed ({type(exc).__name__}); refused (fail closed).",
                proposal_id=self.p.proposal_id,
                invariant="enforcement_unavailable",
            )
        delegation_id = ad.sponsor.delegation_id if ad.sponsor else None
        if ad.outcome == Outcome.UNAVAILABLE:
            d = self._record(ad.model_copy(update={"decisive": True}), recheck=recheck)
            return _Admit(
                stop=self._denied(
                    d, DispatchStatus.UNAVAILABLE, ProposalStatus.UNAVAILABLE, GUIDANCE_UNAVAILABLE
                )
            )
        if ad.outcome == Outcome.BLOCK or ad.outcome not in (Outcome.ALLOW, Outcome.HOLD):
            if ad.outcome != Outcome.BLOCK:  # unknown outcome: fail closed, and say so
                ad = ad.model_copy(
                    update={
                        "outcome": Outcome.BLOCK,
                        "reason": f"Unrecognized enforcement outcome; refused. {ad.reason}",
                    }
                )
            d = self._record(ad.model_copy(update={"decisive": True}), recheck=recheck)
            self._shadow_grant_check(ctx)
            return _Admit(stop=self._denied(d, DispatchStatus.BLOCKED, ProposalStatus.BLOCKED))
        if ad.outcome == Outcome.HOLD and recheck:
            self._record(ad, recheck=True)
            new_delegation = ad.sponsor.delegation_id if ad.sponsor else None
            ids = ""
            if self._sponsor_approved_id or new_delegation:
                ids = (
                    f" (approved delegation {self._sponsor_approved_id or 'none'}; "
                    f"re-check opened delegation {new_delegation or 'none'})"
                )
            return _Admit(
                stop=self._block(
                    DecisionSource.ARMORIQ_SIMULATED if ad.simulated else DecisionSource.ARMORIQ_APPROVAL,
                    "ArmorIQ still requires approval for this action after the approval round; refused" + ids + ".",
                    "armoriq_hold_not_cleared",
                    evidence={
                        "approved_delegation_id": self._sponsor_approved_id,
                        "recheck_delegation_id": new_delegation,
                    },
                    recheck=True,
                )
            )
        self._record(ad, recheck=recheck)
        hold = ad.outcome == Outcome.HOLD

        # 6. grant scope (evaluated on the proposal's own arguments)
        stop = self._adapter_layer("grant", ctx, tool, args, recheck)
        if isinstance(stop, DispatchOutcome):
            return _Admit(stop=stop)

        # 7. domain invariants (+ review requirement)
        res = self._adapter_layer("domain", ctx, tool, args, recheck)
        if isinstance(res, DispatchOutcome):
            return _Admit(stop=res)
        review = res.review if res is not None else None
        if canon_error:
            return _Admit(
                stop=self._block(
                    DecisionSource.DOMAIN,
                    "The server could not derive the canonical arguments for this action; refused.",
                    "canonicalization_failed",
                    evidence={"error": redact_text(canon_error)[:200]},
                    recheck=recheck,
                )
            )
        self._cleared = True
        return _Admit(hold=hold, delegation_id=delegation_id, review=review, canonical=canonical)

    def _adapter_layer(
        self, layer: str, ctx: ToolContext, tool: str, args: dict, recheck: bool
    ) -> DispatchOutcome | AdmissionResult | None:
        source = DecisionSource.GRANT_SCOPE if layer == "grant" else DecisionSource.DOMAIN
        fn = self.rc.adapter.check_grant if layer == "grant" else self.rc.adapter.validate
        try:
            res: AdmissionResult = fn(ctx, tool, args)
        except Exception as exc:
            log.exception("%s check raised for %s", layer, tool)
            return self._block(
                source,
                f"The {layer} check could not be completed ({type(exc).__name__}); refused (fail closed).",
                f"{layer}_check_error",
                recheck=recheck,
            )
        d = res.decision
        if d is not None:
            if not self._adapter_decision_ok(d):
                return self._block(
                    source,
                    "An adapter produced a decision labeled as ArmorIQ; refused.",
                    "mislabeled_decision",
                    recheck=recheck,
                )
            if d.outcome == Outcome.BLOCK:
                d = self._record(d.model_copy(update={"decisive": True, "shadow": False}), recheck=recheck)
                return self._denied(d, DispatchStatus.BLOCKED, ProposalStatus.BLOCKED)
            if d.outcome in (Outcome.UNAVAILABLE, Outcome.ERROR):
                d = self._record(
                    d.model_copy(update={"outcome": Outcome.BLOCK, "decisive": True}), recheck=recheck
                )
                return self._denied(d, DispatchStatus.BLOCKED, ProposalStatus.BLOCKED)
            self._record(d.model_copy(update={"decisive": False}), recheck=recheck)
        return res

    def _shadow_grant_check(self, ctx: ToolContext) -> None:
        """After a decisive ArmorIQ block, ask the grant layer what it WOULD have said (attribution only)."""
        try:
            res = self.rc.adapter.check_grant(ctx, self.tool, self.p.arguments)
        except Exception:
            log.exception("shadow grant check failed")
            return
        d = res.decision
        if d is not None and d.outcome == Outcome.BLOCK and self._adapter_decision_ok(d):
            self._record(d.model_copy(update={"shadow": True, "decisive": False}))

    # step 8 ----------------------------------------------------------------

    def _effective_review(self, admit: _Admit) -> ReviewRequirement | None:
        if admit.review is not None:
            return admit.review
        if admit.hold:
            return self._synthesize_review(admit.canonical)
        return None

    def _synthesize_review(self, canonical: dict[str, Any]) -> ReviewRequirement:
        self._synth_review = True
        targets = canonical.get("order_ids") or canonical.get("targets") or [self.tool]
        return ReviewRequirement(
            reason="ArmorIQ policy requires approval for this action.",
            targets=[str(t) for t in targets],
            payload_digest=digest({"tool": self.tool, "args": canonical}),
            manifest_id=canonical.get("manifest_id")
            if isinstance(canonical.get("manifest_id"), str)
            else None,
            state_constraints={},
        )

    def _approval(self, admit: _Admit) -> DispatchOutcome | None:
        rc, ctx = self.rc, self.ctx
        assert ctx is not None
        review = self._effective_review(admit)
        assert review is not None
        approval = approvals.request(ctx, review, admit.delegation_id)
        self.approval = approval
        by = " and ArmorIQ" if admit.hold else ""
        self._record(
            make_decision(
                rc.run_id,
                DecisionSource.APPROVAL,
                Outcome.HOLD,
                f"Second reviewer required: {review.reason}",
                invariant="second_reviewer_required",
                evidence={
                    "approval_id": approval.approval_id,
                    "payload_digest": approval.payload_digest,
                    "targets": approval.targets,
                    "armoriq_hold": admit.hold,
                },
            )
        )
        _set_proposal_status(self.p.proposal_id, ProposalStatus.HELD)
        previous = _run_status(rc.run_id)
        _set_run_status(rc.run_id, RunStatus.AWAITING_APPROVAL)
        events.emit(
            rc.run_id,
            "approval.requested",
            Actor.REWINDSAFE,
            f"Approval needed for {self.tool}",
            f"A second reviewer must approve the exact payload ({', '.join(approval.targets)}) "
            f"before it can run. Held by VeerIQ{by}.",
            proposal_id=self.p.proposal_id,
            data={"approval": to_jsonable(approval)},
        )

        # Sponsor (ArmorIQ delegation) wait runs in parallel with the human approval wait.
        sponsor_result: dict[str, str] = {}
        sponsor_cancel = threading.Event()
        thread: threading.Thread | None = None
        ttl = max(0.0, (approval.expires_at - utcnow()).total_seconds())
        if admit.delegation_id:

            def _sponsor() -> None:
                try:
                    sponsor_result["v"] = rc.gateway.await_sponsor_approval(
                        rc.run_id, admit.delegation_id or "", ttl, sponsor_cancel
                    )
                except TypeError:  # a gateway without the optional cancel parameter
                    sponsor_result["v"] = rc.gateway.await_sponsor_approval(
                        rc.run_id, admit.delegation_id or "", ttl
                    )  # type: ignore[call-arg]
                except Exception:
                    log.exception("sponsor approval wait failed")
                    sponsor_result["v"] = "timeout"

            thread = threading.Thread(
                target=_sponsor, name=f"sponsor-wait-{approval.approval_id}", daemon=True
            )
            thread.start()

        rec = approvals.wait(approval.approval_id, ttl, rc.cancel)
        sponsor_status: str | None = None
        if thread is not None:
            if rec.status != ApprovalStatus.APPROVED:
                sponsor_cancel.set()
            thread.join(
                timeout=max(0.5, (approval.expires_at - utcnow()).total_seconds())
                if rec.status == ApprovalStatus.APPROVED
                else 5.0
            )
            if thread.is_alive():
                sponsor_cancel.set()
                sponsor_result.setdefault("v", "timeout")
            sponsor_status = (
                "simulated" if rc.gateway.mode == "offline" else sponsor_result.get("v", "timeout")
            )
            try:
                rec = approvals.set_sponsor_status(approval.approval_id, sponsor_status)  # type: ignore[arg-type]
            except Exception:
                log.exception("could not persist sponsor status")
        self.approval = rec
        if previous and previous != RunStatus.AWAITING_APPROVAL.value:
            try:
                _set_run_status(rc.run_id, RunStatus(previous))
            except ValueError:  # pragma: no cover
                pass

        if rec.status == ApprovalStatus.REJECTED:
            who = get_identity(rec.decided_by or "")
            d = self._record(
                make_decision(
                    rc.run_id,
                    DecisionSource.APPROVAL,
                    Outcome.BLOCK,
                    f"{who.name if who else rec.decided_by} rejected the action."
                    + (f" Note: {rec.note}" if rec.note else ""),
                    invariant="approval_rejected",
                    decisive=True,
                    evidence={"approval_id": rec.approval_id, "decided_by": rec.decided_by},
                )
            )
            return self._denied(d, DispatchStatus.HELD_REJECTED, ProposalStatus.REJECTED, GUIDANCE_REJECTED)
        if rec.status != ApprovalStatus.APPROVED:
            why = {
                ApprovalStatus.TIMED_OUT: (
                    "approval_timeout",
                    "No reviewer decided in time; the action was not run.",
                ),
                ApprovalStatus.EXPIRED: (
                    "approval_expired",
                    "The approval window elapsed; the action was not run.",
                ),
                ApprovalStatus.CANCELLED: (
                    "run_cancelled",
                    "The run or demo fixture was cancelled; the action was not run.",
                ),
            }.get(rec.status, ("approval_not_granted", f"Approval ended as {rec.status.value}."))
            events.emit(
                rc.run_id,
                "approval.resolved",
                Actor.REWINDSAFE,
                f"Approval {rec.status.value.replace('_', ' ')} for {self.tool}",
                why[1],
                proposal_id=self.p.proposal_id,
                data={"approval": to_jsonable(rec)},
            )
            d = self._record(
                make_decision(
                    rc.run_id,
                    DecisionSource.APPROVAL,
                    Outcome.BLOCK,
                    why[1],
                    invariant=why[0],
                    decisive=True,
                    evidence={"approval_id": rec.approval_id},
                )
            )
            return self._denied(d, DispatchStatus.HELD_REJECTED, ProposalStatus.REJECTED, GUIDANCE_REJECTED)
        if admit.delegation_id and sponsor_result.get("v") != "approved":
            simulated = rc.gateway.mode == "offline"
            outcome_word = sponsor_result.get("v", "timeout")
            events.emit(
                rc.run_id,
                "approval.resolved",
                Actor.ARMORIQ,
                f"{'Simulated ArmorIQ' if simulated else 'ArmorIQ'} approval {outcome_word} for {self.tool}",
                f"The ArmorIQ delegation was {outcome_word}; both approvals are required, so the action was not run.",
                proposal_id=self.p.proposal_id,
                data={"approval": to_jsonable(rec)},
            )
            d = self._record(
                make_decision(
                    rc.run_id,
                    DecisionSource.ARMORIQ_SIMULATED if simulated else DecisionSource.ARMORIQ_APPROVAL,
                    Outcome.BLOCK,
                    f"The ArmorIQ delegation was {outcome_word}.",
                    invariant="sponsor_not_approved",
                    decisive=True,
                    simulated=simulated,
                    evidence={"delegation_id": admit.delegation_id},
                )
            )
            return self._denied(d, DispatchStatus.HELD_REJECTED, ProposalStatus.REJECTED, GUIDANCE_REJECTED)

        if admit.delegation_id:
            self._sponsor_approved_id = admit.delegation_id

        # Approval never immunizes against later changes: re-run steps 3-7 against current state.
        admit2 = self._admit(recheck=True)
        if admit2.stop:
            return admit2.stop
        review2 = admit2.review
        if self._synth_review and review2 is None:
            review2 = self._synthesize_review(admit2.canonical)
        if review2 is None:
            # Fail closed: the approval is bound to an exact payload; if the current state no longer
            # yields a review requirement there is nothing to compare the approved digest against.
            self._cleared = False
            return self._block(
                DecisionSource.APPROVAL,
                "The review requirement changed after approval; the approved payload can no longer be matched, "
                "so nothing was run.",
                "approval_context_changed",
                evidence={"approved_digest": rec.payload_digest},
                recheck=True,
            )
        if not approvals.payload_matches(
            rec, review2.payload_digest, review2.state_constraints
        ):
            self._cleared = False
            return self._block(
                DecisionSource.APPROVAL,
                "The payload or the state it depends on changed after approval; the approval no longer matches "
                "the exact payload and the action was not run.",
                "payload_changed_after_approval",
                evidence={"approved_digest": rec.payload_digest, "current_digest": review2.payload_digest},
                recheck=True,
            )
        if self.ctx is not None:
            self.ctx.approval = rec
        return None

    # step 9-11 -------------------------------------------------------------

    def _execute(self) -> DispatchOutcome:
        rc, ctx = self.rc, self.ctx
        if not self._cleared or ctx is None:  # structural guarantee: no execute without full clearance
            raise AssertionError("adapter.execute reached without every layer allowing the action")
        if rc.cancel.is_set():
            return self._block(
                DecisionSource.LIFECYCLE, "The run was cancelled before execution.", "run_cancelled"
            )
        self._execution_started = True
        t0 = time.monotonic()
        try:
            ex: ToolExecution = rc.adapter.execute(ctx, self.tool, self.p.arguments)
            self._duration_ms = round((time.monotonic() - t0) * 1000, 1)
        except Exception as exc:
            self._duration_ms = round((time.monotonic() - t0) * 1000, 1)
            log.exception("adapter.execute raised for %s", self.tool)
            d = self._record(
                make_decision(
                    rc.run_id,
                    DecisionSource.PG_TRANSACTION,
                    Outcome.ERROR,
                    f"The tool failed while executing ({type(exc).__name__}). Check the receipt before assuming any effect.",
                    invariant="tool_error",
                    decisive=True,
                )
            )
            _set_proposal_status(self.p.proposal_id, ProposalStatus.FAILED)
            self.p = self.p.model_copy(update={"status": ProposalStatus.FAILED})
            events.emit(
                rc.run_id,
                "execution.rejected",
                Actor.REWINDSAFE,
                f"{self.tool} failed",
                d.reason,
                proposal_id=self.p.proposal_id,
                data={"reason": d.reason, "invariant": "tool_error", "manifest_id": None},
            )
            return DispatchOutcome(
                proposal=self.p,
                status=DispatchStatus.FAILED,
                decisions=self.decisions,
                observation={
                    "status": "failed",
                    "reason": "The tool failed unexpectedly.",
                    "guidance": GUIDANCE_BLOCKED,
                },
                approval=self.approval,
            )

        for ed in ex.decisions:
            self._record(ed.model_copy(update={"shadow": False}))
        if ex.status in (DispatchStatus.STALE, DispatchStatus.BLOCKED) and self.decisions:
            # mark the deciding block so the UI/metrics can attribute it
            for i in range(len(self.decisions) - 1, -1, -1):
                dd = self.decisions[i]
                if dd.outcome == Outcome.BLOCK and not dd.shadow:
                    if not dd.decisive:
                        dd = dd.model_copy(update={"decisive": True})
                        self.decisions[i] = dd
                        with db.autocommit_connection() as conn:
                            conn.execute(
                                "UPDATE runtime.decisions SET decisive = true, body = jsonb_set(body, '{decisive}', 'true') WHERE decision_id = %s",
                                (dd.decision_id,),
                            )
                    break

        pstatus = _PROPOSAL_STATUS.get(ex.status, ProposalStatus.FAILED)
        _set_proposal_status(self.p.proposal_id, pstatus)
        self.p = self.p.model_copy(update={"status": pstatus})
        self._after_execution(ex)

        deciding = next(
            (d for d in reversed(self.decisions) if d.outcome == Outcome.BLOCK and not d.shadow), None
        )
        obs = redact_secrets(ex.observation)
        if ex.status in (DispatchStatus.EXECUTED, DispatchStatus.DUPLICATE):
            obs.setdefault("status", ex.status.value)
        elif ex.status == DispatchStatus.STALE:
            obs.setdefault("status", "stale")
            obs.setdefault("reason", deciding.reason if deciding else ex.summary)
            obs.setdefault("guidance", GUIDANCE_STALE)
        elif ex.status == DispatchStatus.BLOCKED:
            obs.setdefault("status", "blocked")
            obs.setdefault(
                "blocked_by", deciding.source.value if deciding else DecisionSource.PG_PRIVILEGE.value
            )
            obs.setdefault("reason", deciding.reason if deciding else ex.summary)
            obs.setdefault("guidance", GUIDANCE_BLOCKED)
        else:
            obs.setdefault("status", "failed")
            obs.setdefault("reason", ex.summary or "The tool failed.")
            obs.setdefault("guidance", GUIDANCE_BLOCKED)
        return DispatchOutcome(
            proposal=self.p,
            status=ex.status,
            decisions=self.decisions,
            observation=obs,
            manifest=ex.manifest,
            receipt=ex.receipt,
            approval=self.approval,
        )

    def _after_execution(self, ex: ToolExecution) -> None:
        """Events, state-change notice and ArmorIQ report. Never raises: the effect already happened."""
        rc = self.rc
        try:
            pid, seq = self.p.proposal_id, self.prop_seq
            kind = self.spec.kind if self.spec else ToolKind.READ
            if (
                ex.manifest is not None
                and kind == ToolKind.PREPARE
                and not _event_exists_after(rc.run_id, "manifest.prepared", seq)
            ):
                events.emit(
                    rc.run_id,
                    "manifest.prepared",
                    Actor.REWINDSAFE,
                    "Repair manifest prepared",
                    f"Manifest {ex.manifest.manifest_id} stores {len(ex.manifest.changes)} exact change(s) resolved from the approved snapshot.",
                    proposal_id=pid,
                    data={"manifest": to_jsonable(ex.manifest)},
                )
            if ex.status == DispatchStatus.EXECUTED:
                if kind in (ToolKind.READ, ToolKind.PREPARE):
                    result_data = {
                        "tool": self.tool,
                        "summary": ex.summary,
                        "observation_preview": canonical_json(redact_secrets(ex.observation))[:600],
                    }
                    if self.tool == "inspect_snapshot" and isinstance(ex.observation.get("annotations"), list):
                        result_data["annotations"] = redact_secrets(ex.observation["annotations"])
                    events.emit(
                        rc.run_id,
                        "tool.result",
                        Actor.REWINDSAFE,
                        f"{self.tool} completed",
                        ex.summary,
                        proposal_id=pid,
                        data=result_data,
                    )
                elif ex.receipt is not None and not _event_exists_after(
                    rc.run_id, "execution.committed", seq
                ):
                    events.emit(
                        rc.run_id,
                        "execution.committed",
                        Actor.POSTGRES,
                        f"{self.tool} committed",
                        ex.summary,
                        proposal_id=pid,
                        data={"receipt": to_jsonable(ex.receipt)},
                    )
            elif ex.status == DispatchStatus.DUPLICATE:
                if not _event_exists_after(rc.run_id, "execution.duplicate", seq):
                    events.emit(
                        rc.run_id,
                        "execution.duplicate",
                        Actor.REWINDSAFE,
                        "Duplicate apply returned the original receipt",
                        "The same idempotency key and payload were replayed; nothing was applied a second time.",
                        proposal_id=pid,
                        data={"operation_id": ex.receipt.operation_id if ex.receipt else None},
                    )
            elif ex.status in (DispatchStatus.STALE, DispatchStatus.BLOCKED, DispatchStatus.FAILED):
                deciding = next(
                    (d for d in reversed(self.decisions) if d.outcome == Outcome.BLOCK and not d.shadow), None
                )
                if not _event_exists_after(rc.run_id, "execution.rejected", seq):
                    events.emit(
                        rc.run_id,
                        "execution.rejected",
                        Actor.POSTGRES
                        if (deciding and deciding.layer == Layer.POSTGRES)
                        else Actor.REWINDSAFE,
                        f"{self.tool} rejected: no effect"
                        if ex.status != DispatchStatus.FAILED
                        else f"{self.tool} failed",
                        (deciding.reason if deciding else ex.summary) or ex.summary,
                        proposal_id=pid,
                        data={
                            "reason": deciding.reason if deciding else ex.summary,
                            "invariant": deciding.invariant if deciding else None,
                            "manifest_id": ex.manifest.manifest_id
                            if ex.manifest
                            else self.p.arguments.get("manifest_id"),
                        },
                    )
            if ex.state_changed and not _event_exists_after(rc.run_id, "state.changed", seq):
                events.emit(
                    rc.run_id,
                    "state.changed",
                    Actor.SYSTEM,
                    "Application data changed",
                    "",
                    proposal_id=pid,
                    data={"tenant_id": rc.grant.tenant_id},
                )
        except Exception:
            log.exception("post-execution events failed")
        if ex.status in (
            DispatchStatus.EXECUTED,
            DispatchStatus.DUPLICATE,
            DispatchStatus.STALE,
            DispatchStatus.FAILED,
            DispatchStatus.BLOCKED,
        ):
            try:
                ok = ex.status in (DispatchStatus.EXECUTED, DispatchStatus.DUPLICATE)
                summary: dict[str, Any] = {"summary": ex.summary, "status": ex.status.value}
                if ex.receipt is not None:
                    summary["operation_id"] = ex.receipt.operation_id
                if self._duration_ms is not None:
                    summary["duration_ms"] = self._duration_ms
                if not ok:
                    deciding = next(
                        (d for d in reversed(self.decisions) if d.outcome == Outcome.BLOCK and not d.shadow),
                        None,
                    )
                    reason = (deciding.reason if deciding else ex.summary) or ex.summary or ""
                    summary["reason"] = redact_text(reason)[:300]
                    summary["error_message"] = redact_text(reason)[:300]
                    if deciding is not None:
                        summary["blocked_by"] = deciding.source.value
                        summary["invariant"] = deciding.invariant
                name, email = self._approver()
                if name:
                    summary["approved_by"] = name
                    summary["approved_by_email"] = email
                self._reported = True
                # The CANONICAL (server-derived) args are what ArmorIQ checked; report those.
                rc.gateway.report(
                    rc.run_id,
                    self.p.proposal_id,
                    self.tool,
                    self.canonical or self.p.arguments,
                    summary,
                    "success" if ok else "failed",
                )
            except Exception:
                log.exception("gateway.report failed")

    # failure fallback ------------------------------------------------------

    def internal_error(self, exc: BaseException) -> DispatchOutcome:
        log.exception("dispatch failed for %s", self.tool)
        note = (
            "An internal error occurred after execution began; check the receipt before assuming any effect."
            if self._execution_started
            else "An internal error occurred before execution; no effect was applied."
        )
        try:
            self._record(
                make_decision(
                    self.rc.run_id,
                    DecisionSource.TOOL_REGISTRY,
                    Outcome.ERROR,
                    note,
                    invariant="dispatcher_error",
                    decisive=True,
                )
            )
            _set_proposal_status(self.p.proposal_id, ProposalStatus.FAILED)
        except Exception:
            log.exception("could not record dispatcher error")
        self.p = self.p.model_copy(update={"status": ProposalStatus.FAILED})
        return DispatchOutcome(
            proposal=self.p,
            status=DispatchStatus.FAILED,
            decisions=self.decisions,
            observation={"status": "failed", "reason": "Internal error.", "guidance": GUIDANCE_BLOCKED},
            approval=self.approval,
        )


def dispatch(
    rc: RunContext,
    tool: str,
    arguments: dict,
    *,
    rationale: str = "",
    source: str = "agent",
) -> DispatchOutcome:
    """Run one proposed tool call through every layer. See the module docstring."""
    src = source if source in _VALID_SOURCES else "agent"
    args_ok = isinstance(arguments, dict)
    try:
        safe_args = to_jsonable(arguments) if args_ok else {}
    except (TypeError, ValueError):
        args_ok, safe_args = False, {}
    proposal = ActionProposal(
        proposal_id=new_id("prp"),
        run_id=rc.run_id,
        step_index=rc.step_index,
        tool=tool,
        arguments=safe_args,
        rationale=redact_text(rationale)[:1000],
        source=src,  # type: ignore[arg-type]
        status=ProposalStatus.PENDING,
        created_at=utcnow(),
    )
    rc.step_index += 1
    _insert_proposal(proposal)  # 1. persist (status pending)
    ev = events.emit(
        rc.run_id,
        "agent.proposal",
        {"boundary_harness": Actor.HARNESS, "operator": Actor.OPERATOR}.get(src, Actor.AGENT),
        f"Proposed {tool}",
        redact_text(rationale)[:300],
        proposal_id=proposal.proposal_id,
        data={
            "tool": tool,
            "arguments": safe_args,
            "rationale": redact_text(rationale)[:1000],
            "source": src,
            "step_index": proposal.step_index,
        },
    )
    specs = {s.name: s for s in rc.adapter.tool_specs()}
    d = _Dispatcher(rc, proposal, specs.get(tool))
    d.prop_seq = ev.seq
    if not args_ok:
        return d._block(
            DecisionSource.TOOL_REGISTRY, "Tool arguments must be a JSON object.", "schema_violation"
        )
    try:
        return d.run()
    except Exception as exc:  # noqa: BLE001 - never crash the agent loop / server
        return d.internal_error(exc)
