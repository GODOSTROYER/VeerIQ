"""Workflow adapter protocol + registry (architecture.md 4.5).

The runtime is workflow-agnostic: a workflow supplies a :class:`WorkflowAdapter`
(tools, scenarios, grant template, admission checks and the SOLE executor).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from rewindsafe.contracts import (
    ActionProposal,
    ApprovalRecord,
    Decision,
    DecisionSource,
    DispatchStatus,
    ExecutionManifest,
    ExecutionReceipt,
    Identity,
    InvariantCheck,
    Layer,
    Outcome,
    ScenarioSpec,
    TaskGrant,
    ToolSpec,
)
from rewindsafe.runtime.canonical import new_id, utcnow


@dataclass
class ToolContext:
    """Passed to adapter handlers. ``approval`` is set when executing an approved action."""

    run_id: str
    proposal: ActionProposal
    grant: TaskGrant
    identity: Identity
    scenario: ScenarioSpec
    enforcement_mode: str
    sdk_version: str | None = None
    approval: ApprovalRecord | None = None


class ReviewRequirement(BaseModel):
    reason: str
    targets: list[str]
    payload_digest: str
    manifest_id: str | None = None
    state_constraints: dict[str, Any] = Field(default_factory=dict)


class AdmissionResult(BaseModel):
    """Adapter verdict for one layer. ``decision=None`` means allow with nothing notable to record."""

    decision: Decision | None = None
    canonical_args: dict[str, Any] | None = None  # advisory; the dispatcher uses adapter.canonicalize()
    review: ReviewRequirement | None = None


class ToolExecution(BaseModel):
    status: DispatchStatus  # EXECUTED | STALE | FAILED | DUPLICATE | BLOCKED
    observation: dict[str, Any] = Field(default_factory=dict)  # sanitized, JSON-safe; returned to the agent
    summary: str = ""
    decisions: list[Decision] = Field(default_factory=list)
    manifest: ExecutionManifest | None = None
    receipt: ExecutionReceipt | None = None
    state_changed: bool = False


@runtime_checkable
class WorkflowAdapter(Protocol):
    workflow_id: str  # "rewindsafe.order_repair"
    mcp_name: str  # "rewindsafe-recovery"

    def tool_specs(self) -> list[ToolSpec]: ...

    def scenarios(self) -> list[ScenarioSpec]: ...

    def build_grant(
        self, scenario: ScenarioSpec, identity: Identity, fixture_generation: int
    ) -> TaskGrant: ...

    def plan_tool_calls(self, grant: TaskGrant) -> list[dict]: ...

    def canonicalize(self, ctx: ToolContext, tool: str, args: dict) -> dict: ...

    def check_grant(self, ctx: ToolContext, tool: str, args: dict) -> AdmissionResult: ...

    def validate(self, ctx: ToolContext, tool: str, args: dict) -> AdmissionResult: ...

    def execute(self, ctx: ToolContext, tool: str, args: dict) -> ToolExecution: ...

    def protected_checks(self, tenant_id: str) -> list[InvariantCheck]: ...

    def app_state(self, tenant_id: str) -> dict: ...


# ─── registry ─────────────────────────────────────────────────────────────

_registry: dict[str, WorkflowAdapter] = {}
_registry_lock = threading.Lock()


def register_adapter(adapter: WorkflowAdapter) -> None:
    with _registry_lock:
        _registry[adapter.workflow_id] = adapter


def get_adapter(workflow_id: str) -> WorkflowAdapter:
    with _registry_lock:
        try:
            return _registry[workflow_id]
        except KeyError:
            raise KeyError(
                f"no workflow adapter registered for {workflow_id!r} (registered: {sorted(_registry)})"
            ) from None


def all_adapters() -> list[WorkflowAdapter]:
    with _registry_lock:
        return list(_registry.values())


# ─── decision factory (shared by every layer) ─────────────────────────────

_LAYER_BY_SOURCE: dict[DecisionSource, Layer] = {
    DecisionSource.ARMORIQ_PLAN_BINDING: Layer.ARMORIQ,
    DecisionSource.ARMORIQ_ENFORCE: Layer.ARMORIQ,
    DecisionSource.ARMORIQ_TOKEN_ISSUANCE: Layer.ARMORIQ,
    DecisionSource.ARMORIQ_APPROVAL: Layer.ARMORIQ,
    DecisionSource.ARMORIQ_SIMULATED: Layer.ARMORIQ,
    DecisionSource.GRANT_SCOPE: Layer.GRANT,
    DecisionSource.DOMAIN: Layer.DOMAIN,
    DecisionSource.APPROVAL: Layer.APPROVAL,
    DecisionSource.TOOL_REGISTRY: Layer.RUNTIME,
    DecisionSource.LIFECYCLE: Layer.RUNTIME,
    DecisionSource.PG_PRIVILEGE: Layer.POSTGRES,
    DecisionSource.PG_TRANSACTION: Layer.POSTGRES,
}


def make_decision(
    run_id: str,
    source: DecisionSource,
    outcome: Outcome,
    reason: str,
    *,
    proposal_id: str | None = None,
    layer: Layer | None = None,
    invariant: str | None = None,
    decisive: bool = False,
    shadow: bool = False,
    simulated: bool = False,
    latency_ms: float | None = None,
    sponsor: Any = None,
    evidence: dict[str, Any] | None = None,
) -> Decision:
    """Build a :class:`Decision`; the layer defaults from the source so it can never mislabel."""
    return Decision(
        decision_id=new_id("dec"),
        run_id=run_id,
        proposal_id=proposal_id,
        layer=layer or _LAYER_BY_SOURCE[source],
        source=source,
        outcome=outcome,
        decisive=decisive,
        shadow=shadow,
        simulated=simulated,
        reason=reason,
        invariant=invariant,
        latency_ms=latency_ms,
        sponsor=sponsor,
        evidence=evidence or {},
        created_at=utcnow(),
    )
