"""Shared, versioned contracts for the RewindSafe authority runtime.

Every module (runtime, workflow adapters, agent loop, API, tests) imports these
types. The frontend mirrors them in ``frontend/src/api/types.ts``. Change them
only through the integrator, and bump ``CONTRACT_VERSION`` when a shape changes.

Naming map to the master brief:
  TaskGrant           -> TaskGrant
  ActionProposal      -> ActionProposal
  ExecutionManifest   -> ExecutionManifest
  SponsorDecision     -> Decision with layer=ARMORIQ (``sponsor`` populated)
  DomainDecision      -> Decision with layer in {GRANT, DOMAIN, POSTGRES, APPROVAL, RUNTIME}
  ApprovalRecord      -> ApprovalRecord
  ExecutionReceipt    -> ExecutionReceipt
  RunEvent            -> RunEvent
  WorkflowAdapter     -> rewindsafe.runtime.adapter.WorkflowAdapter (Protocol)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "1.0"


class _Model(BaseModel):
    model_config = ConfigDict(use_enum_values=False, populate_by_name=True)


# ─── Enumerations ──────────────────────────────────────────────────────────


class Layer(str, Enum):
    """Defense layer that produced a decision. Ordered outermost → innermost."""

    ARMORIQ = "armoriq"  # ArmorIQ signed intent plan + platform policy
    GRANT = "grant"  # RewindSafe task-grant scope (tenant, resources, fields, tools)
    DOMAIN = "domain"  # RewindSafe domain invariants (snapshot values, tombstones, holds, versions)
    APPROVAL = "approval"  # Human second-reviewer approval bound to exact payload
    POSTGRES = "postgres"  # Database role privileges + transactional checks
    RUNTIME = "runtime"  # Tool registry, schema validation, run lifecycle, limits


class DecisionSource(str, Enum):
    """Exact component that issued a decision. Never label a local check as ArmorIQ."""

    ARMORIQ_PLAN_BINDING = "armoriq.sdk.plan_binding"  # SDK check vs backend-signed plan (tool-not-in-plan)
    ARMORIQ_ENFORCE = "armoriq.backend.enforce"  # POST /iap/sdk/enforce policy decision
    ARMORIQ_TOKEN_ISSUANCE = "armoriq.backend.token_issuance"  # /iap/sdk/token refused / issued
    ARMORIQ_APPROVAL = "armoriq.backend.approval"  # delegation approval status
    ARMORIQ_SIMULATED = "armoriq.offline_simulation"  # OFFLINE MODE ONLY — clearly labeled simulation
    GRANT_SCOPE = "rewindsafe.grant_scope"
    DOMAIN = "rewindsafe.domain"
    APPROVAL = "rewindsafe.approval"
    TOOL_REGISTRY = "rewindsafe.tool_registry"
    LIFECYCLE = "rewindsafe.lifecycle"
    PG_PRIVILEGE = "postgres.privilege"
    PG_TRANSACTION = "postgres.transaction"


class Outcome(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    HOLD = "hold"
    UNAVAILABLE = "unavailable"  # enforcement service unreachable → fail closed, NOT a policy denial
    ERROR = "error"
    SKIPPED = "skipped"


class ToolKind(str, Enum):
    READ = "read"  # guarded read of scoped data
    PREPARE = "prepare"  # creates an immutable manifest; no application-data mutation
    MUTATE = "mutate"  # mutates application data (credentialed executor)
    ADMIN = "admin"  # privileged authority mutation (operator-only; never in an agent grant)


class GrantStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class RunStatus(str, Enum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_RUN_STATUSES = {
    RunStatus.SUCCEEDED,
    RunStatus.PARTIALLY_SUCCEEDED,
    RunStatus.BLOCKED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}


class ProposalStatus(str, Enum):
    PENDING = "pending"
    EXECUTED = "executed"  # passed every layer and ran (read, prepare or mutate)
    BLOCKED = "blocked"  # a layer blocked it before any effect
    HELD = "held"  # awaiting approval
    REJECTED = "rejected"  # approval rejected / timed out / expired
    STALE = "stale"  # preconditions changed between preview and commit
    FAILED = "failed"  # tool error after admission
    UNAVAILABLE = "unavailable"  # enforcement unavailable → fail closed
    DUPLICATE = "duplicate"  # idempotent replay returned the original receipt


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class InvariantStatus(str, Enum):
    PRESERVED = "preserved"  # protected state unchanged (good)
    REPAIRED = "repaired"  # intended repair applied (good)
    PENDING = "pending"  # repair not yet applied
    VIOLATED = "violated"  # protected state changed (bad — must never happen)


class Actor(str, Enum):
    AGENT = "agent"
    ARMORIQ = "armoriq"
    REWINDSAFE = "rewindsafe"
    POSTGRES = "postgres"
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    SYSTEM = "system"
    HARNESS = "harness"  # deterministic boundary harness


# ─── Identities ────────────────────────────────────────────────────────────


class Identity(_Model):
    """Local demo identity. Explicitly labeled as demo auth in the UI."""

    identity_id: str
    name: str
    email: str
    role: Literal["operator", "reviewer"]
    tenant_id: str
    title: str
    initials: str
    color: str  # hex accent for avatar


# ─── Grants ────────────────────────────────────────────────────────────────


class GrantLimits(_Model):
    max_commits: int = 1
    max_rows_per_commit: int = 5
    max_steps: int = 20
    max_replans: int = 3
    approval_ttl_seconds: int = 600
    review_threshold_cents: int = 500_000  # restoring more than $5,000 needs a second reviewer


class TaskGrant(_Model):
    """Human-reviewed authority ceiling for one task. Created ONLY by trusted code
    from a typed workflow template; the model can never widen it."""

    grant_id: str
    workflow: str  # e.g. "rewindsafe.order_repair"
    scenario_id: str
    principal: str  # identity_id of the authenticated operator
    principal_email: str
    tenant_id: str
    incident_id: Optional[str] = None
    purpose: str
    allowed_tools: list[str]  # tool names the signed ArmorIQ plan will contain
    resources: dict[str, list[str]]  # e.g. {"order": ["O-2041","O-2042"], "snapshot": ["SNAP-..."]}
    reviewable: dict[str, list[str]] = Field(default_factory=dict)  # resources that need a second reviewer
    fields: list[str] = Field(default_factory=list)  # repairable columns
    prohibited_effects: list[str] = Field(default_factory=list)  # human-readable hard prohibitions
    source_constraints: dict[str, Any] = Field(default_factory=dict)  # {"snapshot_id":..., "snapshot_digest":...}
    limits: GrantLimits = Field(default_factory=GrantLimits)
    status: GrantStatus = GrantStatus.DRAFT
    commits_used: int = 0
    created_at: datetime
    expires_at: datetime
    authorized_at: Optional[datetime] = None
    authorized_by: Optional[str] = None
    fixture_generation: int
    grant_digest: str  # sha256 over the canonical authority-bearing fields


# ─── Proposals, manifests, decisions ───────────────────────────────────────


class ActionProposal(_Model):
    """Untrusted request to call a tool. Produced by the agent, the boundary
    harness, or an MCP client. Never authority by itself."""

    proposal_id: str
    run_id: str
    step_index: int
    tool: str
    arguments: dict[str, Any]
    rationale: str = ""  # short operator-facing explanation (not chain-of-thought)
    source: Literal["agent", "boundary_harness", "operator", "mcp"] = "agent"
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime


class ManifestChange(_Model):
    entity: str  # "order"
    row_id: str  # "O-2041"
    field: str  # "total_cents"
    op: Literal["update", "delete", "anonymize"] = "update"
    current_value: Any = None  # value observed at preview time
    new_value: Any = None  # value resolved by TRUSTED code from the approved snapshot
    source_path: str = ""  # e.g. "snapshot:SNAP-2026-10-05-0000Z/orders/O-2041/total_cents"


class ManifestPreconditions(_Model):
    authority_epoch: int
    row_versions: dict[str, int]  # row_id -> row_version at preview
    fixture_generation: int
    tombstone_free: list[str] = Field(default_factory=list)  # entities verified not deleted
    hold_free: list[str] = Field(default_factory=list)  # entities verified not under an active hold


class ExecutionManifest(_Model):
    """Immutable, server-stored description of exact effects. The executor accepts
    only (manifest_id, manifest_digest) — never SQL or model-supplied values."""

    manifest_id: str
    grant_id: str
    run_id: str
    principal: str
    tenant_id: str
    workflow: str
    snapshot_id: str
    snapshot_digest: str
    changes: list[ManifestChange]
    preconditions: ManifestPreconditions
    restored_value_cents: int = 0  # sum of positive total_cents deltas (drives review threshold)
    requires_review: bool = False
    review_reason: Optional[str] = None
    content_digest: str  # sha256 over canonical content (everything above except status/created_at)
    status: Literal["prepared", "committed", "stale", "rejected", "superseded"] = "prepared"
    created_at: datetime


class SponsorDetail(_Model):
    """ArmorIQ-specific evidence attached to an ARMORIQ-layer decision."""

    mode: Literal["live", "offline"]
    session_mode: Optional[str] = None  # "sdk" | "local" | "proxy"
    sdk_version: Optional[str] = None
    raw_action: Optional[str] = None  # enforcementAction value as returned
    matched_policy: Optional[str] = None
    delegation_id: Optional[str] = None
    plan_id: Optional[str] = None
    plan_hash: Optional[str] = None
    token_id: Optional[str] = None
    obligations: list[dict[str, Any]] = Field(default_factory=list)
    sanitized_response: dict[str, Any] = Field(default_factory=dict)  # never contains secrets/tokens


class Decision(_Model):
    """One layer's verdict on one proposal. ``decisive`` marks the layer that
    determined the outcome; ``shadow`` decisions were evaluated after a decisive
    block purely for attribution ("would also have blocked")."""

    decision_id: str
    run_id: str
    proposal_id: Optional[str] = None
    layer: Layer
    source: DecisionSource
    outcome: Outcome
    decisive: bool = False
    shadow: bool = False
    simulated: bool = False  # True only for ARMORIQ_SIMULATED
    reason: str
    invariant: Optional[str] = None  # machine id, e.g. "tenant_scope", "snapshot_value", "tombstone"
    latency_ms: Optional[float] = None
    sponsor: Optional[SponsorDetail] = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


# Aliases that match the master brief's vocabulary.
SponsorDecision = Decision
DomainDecision = Decision


class PlanBinding(_Model):
    """Result of binding a grant to an ArmorIQ signed intent plan."""

    mode: Literal["live", "offline"]
    simulated: bool
    plan_id: Optional[str] = None
    plan_hash: Optional[str] = None
    token_id: Optional[str] = None
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    steps: list[str] = Field(default_factory=list)  # tool names in the signed plan
    sdk_version: Optional[str] = None
    session_mode: Optional[str] = None
    error: Optional[str] = None
    latency_ms: Optional[float] = None  # wall time of the plan-signing call
    matched_policies: list[str] = Field(default_factory=list)  # policy names ArmorIQ snapshotted into the plan


# ─── Approvals ─────────────────────────────────────────────────────────────


class ApprovalRecord(_Model):
    approval_id: str
    run_id: str
    grant_id: str
    proposal_id: str
    tool: str
    manifest_id: Optional[str] = None
    payload_digest: str  # exact canonical payload being approved
    targets: list[str]
    reason: str  # why review is required
    requested_by: str  # identity_id of the run's operator
    requested_at: datetime
    expires_at: datetime
    state_constraints: dict[str, Any]  # {"authority_epoch":..,"row_versions":{..},"fixture_generation":..}
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    note: Optional[str] = None
    sponsor_delegation_id: Optional[str] = None  # ArmorIQ delegation id when ArmorIQ issued a HOLD
    sponsor_status: Optional[Literal["pending", "approved", "rejected", "timeout", "simulated"]] = None


# ─── Receipts, invariants, events ──────────────────────────────────────────


class InvariantCheck(_Model):
    check_id: str  # e.g. "tombstone:C-1003"
    label: str  # "Deleted customer Orion Freight stays deleted"
    category: Literal["repair", "tombstone", "access", "later_update", "tenant_isolation", "hold"]
    status: InvariantStatus
    detail: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class ReceiptChange(_Model):
    row_id: str
    field: str
    before: Any = None
    after: Any = None


class ExecutionReceipt(_Model):
    operation_id: str
    idempotency_key: str
    grant_id: str
    run_id: str
    manifest_id: str
    manifest_digest: str
    result: Literal["committed", "failed"]
    changes: list[ReceiptChange] = Field(default_factory=list)
    checks: list[InvariantCheck] = Field(default_factory=list)  # before/after invariant evidence
    effect_counts: dict[str, int] = Field(default_factory=dict)  # rows_updated, prohibited_handler_entries...
    decision_sources: list[str] = Field(default_factory=list)
    enforcement_mode: Literal["live", "offline"]
    sdk_version: Optional[str] = None
    fixture_generation: int
    approval_id: Optional[str] = None
    created_at: datetime
    committed_at: Optional[datetime] = None
    receipt_digest: str


class RunEvent(_Model):
    """Append-only, sequence-numbered event. ``title``/``detail`` are human copy
    rendered directly by the UI; ``data`` is a safe structured payload."""

    seq: int
    run_id: str
    ts: datetime
    type: str  # see docs/architecture.md §Events for the closed list
    actor: Actor
    title: str
    detail: str = ""
    proposal_id: Optional[str] = None
    decision: Optional[Decision] = None
    data: dict[str, Any] = Field(default_factory=dict)


class Run(_Model):
    run_id: str
    grant_id: str
    scenario_id: str
    workflow: str
    planner: str  # "scripted" | "anthropic:<model>" | "openai:<model>"
    planner_kind: Literal["scripted", "llm", "harness"]
    enforcement_mode: Literal["live", "offline"]
    status: RunStatus
    outcome_summary: Optional[str] = None
    steps_used: int = 0
    replans_used: int = 0
    plan: Optional[PlanBinding] = None
    fixture_generation: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ─── Scenarios & tools ─────────────────────────────────────────────────────


class ExternalEvent(_Model):
    """Deterministic out-of-band change injected by the scenario runner (e.g. a
    finance hold placed between preview and commit). Executed via the trusted
    authority-admin path, never by the agent."""

    trigger_after_tool: str  # fire right after this tool succeeds...
    occurrence: int = 1  # ...for the Nth time
    action: Literal["place_hold", "add_tombstone", "revoke_access"]
    target: str
    reason: str
    actor_label: str  # "Finance (dispute desk)"


class ScenarioSpec(_Model):
    scenario_id: str  # "clean" | "poisoned" | "boundary" | "stale" | "review"
    workflow: str
    title: str
    tagline: str
    description: str
    kind: Literal["baseline", "flagship", "boundary", "race", "approval"]
    order: int
    inject_annotation: bool = False
    default_planner: Literal["auto", "scripted", "llm", "harness"] = "auto"
    grant_template: dict[str, Any]  # resources/reviewable/fields/limits used by trusted grant builder
    external_events: list[ExternalEvent] = Field(default_factory=list)
    expected_outcome: str = ""
    highlights: list[str] = Field(default_factory=list)  # bullet copy for the launcher card


class ToolSpec(_Model):
    name: str
    title: str
    description: str  # shown to the LLM
    kind: ToolKind
    input_schema: dict[str, Any]
    mutator: bool = False  # True for MUTATE and ADMIN → handler entries are counted


class DispatchStatus(str, Enum):
    EXECUTED = "executed"
    BLOCKED = "blocked"
    HELD_REJECTED = "held_rejected"
    STALE = "stale"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    DUPLICATE = "duplicate"


class DispatchOutcome(_Model):
    proposal: ActionProposal
    status: DispatchStatus
    decisions: list[Decision] = Field(default_factory=list)
    observation: dict[str, Any] = Field(default_factory=dict)  # sanitized result returned to the agent
    manifest: Optional[ExecutionManifest] = None
    receipt: Optional[ExecutionReceipt] = None
    approval: Optional[ApprovalRecord] = None
