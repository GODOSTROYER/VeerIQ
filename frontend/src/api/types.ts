/**
 * Mirrors backend/rewindsafe/contracts.py (CONTRACT_VERSION 1.0) exactly.
 * Enums are string unions, datetimes are ISO-8601 strings.
 * API response shapes follow docs/architecture.md section 8.
 */

export const CONTRACT_VERSION = '1.0'

// ─── Enumerations ──────────────────────────────────────────────────────────

export type Layer = 'armoriq' | 'grant' | 'domain' | 'approval' | 'postgres' | 'runtime'

export type DecisionSource =
  | 'armoriq.sdk.plan_binding'
  | 'armoriq.backend.enforce'
  | 'armoriq.backend.token_issuance'
  | 'armoriq.backend.approval'
  | 'armoriq.offline_simulation'
  | 'rewindsafe.grant_scope'
  | 'rewindsafe.domain'
  | 'rewindsafe.approval'
  | 'rewindsafe.tool_registry'
  | 'rewindsafe.lifecycle'
  | 'postgres.privilege'
  | 'postgres.transaction'

export type Outcome = 'allow' | 'block' | 'hold' | 'unavailable' | 'error' | 'skipped'

export type ToolKind = 'read' | 'prepare' | 'mutate' | 'admin'

export type GrantStatus = 'draft' | 'active' | 'exhausted' | 'expired' | 'revoked'

export type RunStatus =
  | 'created'
  | 'authorized'
  | 'planning'
  | 'awaiting_approval'
  | 'executing'
  | 'succeeded'
  | 'partially_succeeded'
  | 'blocked'
  | 'failed'
  | 'cancelled'

export const TERMINAL_RUN_STATUSES: readonly RunStatus[] = [
  'succeeded',
  'partially_succeeded',
  'blocked',
  'failed',
  'cancelled',
]

export type ProposalStatus =
  | 'pending'
  | 'executed'
  | 'blocked'
  | 'held'
  | 'rejected'
  | 'stale'
  | 'failed'
  | 'unavailable'
  | 'duplicate'

export type ApprovalStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'timed_out'
  | 'expired'
  | 'cancelled'

export type InvariantStatus = 'preserved' | 'repaired' | 'pending' | 'violated'

export type Actor =
  | 'agent'
  | 'armoriq'
  | 'rewindsafe'
  | 'postgres'
  | 'operator'
  | 'reviewer'
  | 'system'
  | 'harness'

export type DispatchStatus =
  | 'executed'
  | 'blocked'
  | 'held_rejected'
  | 'stale'
  | 'failed'
  | 'unavailable'
  | 'duplicate'

// ─── Identities ────────────────────────────────────────────────────────────

export interface Identity {
  identity_id: string
  name: string
  email: string
  role: 'operator' | 'reviewer'
  tenant_id: string
  title: string
  initials: string
  color: string
}

// ─── Grants ────────────────────────────────────────────────────────────────

export interface GrantLimits {
  max_commits: number
  max_rows_per_commit: number
  max_steps: number
  max_replans: number
  approval_ttl_seconds: number
  review_threshold_cents: number
}

export interface TaskGrant {
  grant_id: string
  workflow: string
  scenario_id: string
  principal: string
  principal_email: string
  tenant_id: string
  incident_id: string | null
  purpose: string
  allowed_tools: string[]
  resources: Record<string, string[]>
  reviewable: Record<string, string[]>
  fields: string[]
  prohibited_effects: string[]
  source_constraints: Record<string, unknown>
  limits: GrantLimits
  status: GrantStatus
  commits_used: number
  created_at: string
  expires_at: string
  authorized_at: string | null
  authorized_by: string | null
  fixture_generation: number
  grant_digest: string
}

// ─── Proposals, manifests, decisions ───────────────────────────────────────

export type ProposalSource = 'agent' | 'boundary_harness' | 'operator' | 'mcp'

export interface ActionProposal {
  proposal_id: string
  run_id: string
  step_index: number
  tool: string
  arguments: Record<string, unknown>
  rationale: string
  source: ProposalSource
  status: ProposalStatus
  created_at: string
}

export interface ManifestChange {
  entity: string
  row_id: string
  field: string
  op: 'update' | 'delete' | 'anonymize'
  current_value: unknown
  new_value: unknown
  source_path: string
}

export interface ManifestPreconditions {
  authority_epoch: number
  row_versions: Record<string, number>
  fixture_generation: number
  tombstone_free: string[]
  hold_free: string[]
}

export type ManifestStatus = 'prepared' | 'committed' | 'stale' | 'rejected' | 'superseded'

export interface ExecutionManifest {
  manifest_id: string
  grant_id: string
  run_id: string
  principal: string
  tenant_id: string
  workflow: string
  snapshot_id: string
  snapshot_digest: string
  changes: ManifestChange[]
  preconditions: ManifestPreconditions
  restored_value_cents: number
  requires_review: boolean
  review_reason: string | null
  content_digest: string
  status: ManifestStatus
  created_at: string
}

export interface SponsorDetail {
  mode: 'live' | 'offline'
  session_mode: string | null
  sdk_version: string | null
  raw_action: string | null
  matched_policy: string | null
  delegation_id: string | null
  plan_id: string | null
  plan_hash: string | null
  token_id: string | null
  obligations: Record<string, unknown>[]
  sanitized_response: Record<string, unknown>
}

export interface Decision {
  decision_id: string
  run_id: string
  proposal_id: string | null
  layer: Layer
  source: DecisionSource
  outcome: Outcome
  decisive: boolean
  shadow: boolean
  simulated: boolean
  reason: string
  invariant: string | null
  latency_ms: number | null
  sponsor: SponsorDetail | null
  evidence: Record<string, unknown>
  created_at: string
}

export interface PlanBinding {
  mode: 'live' | 'offline'
  simulated: boolean
  plan_id: string | null
  plan_hash: string | null
  token_id: string | null
  issued_at: string | null
  expires_at: string | null
  steps: string[]
  sdk_version: string | null
  session_mode: string | null
  error: string | null
  /** Round-trip time of the signed-plan request (live mode only). */
  latency_ms?: number | null
  matched_policies?: string[]
}

// ─── Approvals ─────────────────────────────────────────────────────────────

export type SponsorStatus = 'pending' | 'approved' | 'rejected' | 'timeout' | 'simulated'

export interface ApprovalRecord {
  approval_id: string
  run_id: string
  grant_id: string
  proposal_id: string
  tool: string
  manifest_id: string | null
  payload_digest: string
  targets: string[]
  reason: string
  requested_by: string
  requested_at: string
  expires_at: string
  state_constraints: Record<string, unknown>
  status: ApprovalStatus
  decided_by: string | null
  decided_at: string | null
  note: string | null
  sponsor_delegation_id: string | null
  sponsor_status: SponsorStatus | null
}

/** GET /approvals returns approval records plus the manifest preview when one exists. */
export interface ApprovalWithPreview extends ApprovalRecord {
  manifest?: ExecutionManifest | null
}

// ─── Receipts, invariants, events ──────────────────────────────────────────

export type InvariantCategory =
  | 'repair'
  | 'tombstone'
  | 'access'
  | 'later_update'
  | 'tenant_isolation'
  | 'hold'

export interface InvariantCheck {
  check_id: string
  label: string
  category: InvariantCategory
  status: InvariantStatus
  detail: string
  evidence: Record<string, unknown>
}

export interface ReceiptChange {
  row_id: string
  field: string
  before: unknown
  after: unknown
}

export interface ExecutionReceipt {
  operation_id: string
  idempotency_key: string
  grant_id: string
  run_id: string
  manifest_id: string
  manifest_digest: string
  result: 'committed' | 'failed'
  changes: ReceiptChange[]
  checks: InvariantCheck[]
  effect_counts: Record<string, number>
  decision_sources: string[]
  enforcement_mode: 'live' | 'offline'
  sdk_version: string | null
  fixture_generation: number
  approval_id: string | null
  created_at: string
  committed_at: string | null
  receipt_digest: string
}

/** Closed list of event types the backend emits (architecture.md section 4.3). */
export type RunEventType =
  | 'run.created'
  | 'run.status'
  | 'plan.requested'
  | 'plan.bound'
  | 'plan.bind_failed'
  | 'agent.note'
  | 'agent.proposal'
  | 'decision'
  | 'tool.result'
  | 'manifest.prepared'
  | 'approval.requested'
  | 'approval.resolved'
  | 'execution.committed'
  | 'execution.rejected'
  | 'execution.duplicate'
  | 'replan'
  | 'external.change'
  | 'state.changed'
  | 'telemetry.delivery'
  | 'run.finished'

export interface RunEvent {
  seq: number
  run_id: string
  ts: string
  /** Typed as string in the contract; compare with RunEventType values. */
  type: string
  actor: Actor
  title: string
  detail: string
  proposal_id: string | null
  decision: Decision | null
  data: Record<string, unknown>
}

export interface Run {
  run_id: string
  grant_id: string
  scenario_id: string
  workflow: string
  planner: string
  planner_kind: 'scripted' | 'llm' | 'harness'
  enforcement_mode: 'live' | 'offline'
  status: RunStatus
  outcome_summary: string | null
  steps_used: number
  replans_used: number
  plan: PlanBinding | null
  fixture_generation: number
  created_by: string
  created_at: string
  updated_at: string
  finished_at: string | null
  /** metadata.planner_label is the human label the server chose for this run's planner. */
  metadata: Record<string, unknown> & { planner_label?: string }
}

// ─── Scenarios & tools ─────────────────────────────────────────────────────

export interface ExternalEvent {
  trigger_after_tool: string
  occurrence: number
  action: 'place_hold' | 'add_tombstone' | 'revoke_access'
  target: string
  reason: string
  actor_label: string
}

export type ScenarioKind = 'baseline' | 'flagship' | 'boundary' | 'race' | 'approval'

export interface ScenarioSpec {
  scenario_id: string
  workflow: string
  title: string
  tagline: string
  description: string
  kind: ScenarioKind
  order: number
  inject_annotation: boolean
  default_planner: 'auto' | 'scripted' | 'llm' | 'harness'
  grant_template: Record<string, unknown>
  external_events: ExternalEvent[]
  expected_outcome: string
  highlights: string[]
}

export interface ToolSpec {
  name: string
  title: string
  description: string
  kind: ToolKind
  input_schema: Record<string, unknown>
  mutator: boolean
}

export interface DispatchOutcome {
  proposal: ActionProposal
  status: DispatchStatus
  decisions: Decision[]
  observation: Record<string, unknown>
  manifest: ExecutionManifest | null
  receipt: ExecutionReceipt | null
  approval: ApprovalRecord | null
}

// ─── API responses (architecture.md section 8) ─────────────────────────────

export type PlannerProvider = 'anthropic' | 'groq' | 'openai' | string

export type ReadinessState = 'verified' | 'unverified' | 'failed' | 'simulated'

/** Result of the gateway's lightweight live probe (bind a one-tool plan, run one check). */
export interface EnforcementReadiness {
  state: ReadinessState
  checked_at: string | null
  detail: string | null
  matched_policy: string | null
  plan_latency_ms: number | null
  check_latency_ms: number | null
}

export interface SystemWarning {
  level: 'info' | 'warn' | 'error'
  code: string
  message: string
}

export interface SystemStatus {
  enforcement: {
    mode: 'live' | 'offline'
    simulated: boolean
    sdk_version: string | null
    session_mode: string | null
    env: string | null
    configured: boolean
    user_email_set: boolean
    readiness?: EnforcementReadiness | null
  }
  planner: {
    kind: 'scripted' | 'llm' | 'harness'
    name: string
    provider?: PlannerProvider | null
    model?: string | null
    configured_llm: boolean
    available_providers?: string[]
  }
  database: { ok: boolean }
  fixture_generation: number
  contract_version: string
  /** Objects since contract C7; older servers sent plain strings (normalised by normaliseWarnings). */
  warnings: (SystemWarning | string)[]
}

export type OrderCondition =
  | 'damaged'
  | 'healthy'
  | 'changed_after_snapshot'
  | 'deleted_tombstoned'
  | 'on_hold'

export interface OrderRow {
  order_id: string
  customer_id: string
  customer_name?: string | null
  status: string
  total_cents: number
  currency: string
  shipping_region: string | null
  item_summary: string
  owner_account?: string
  row_version: number
  updated_at: string
  updated_by: string
  /** Server-side assessment against the approved snapshot (GET /app/state). */
  condition?: OrderCondition | null
  on_hold?: boolean
}

export interface DeletedEntity {
  entity_type: 'customer' | 'order'
  entity_id: string
  display_name: string
  deleted_at: string
  reason: string
  deleted_by: string
}

export interface AccessGrantRow {
  grant_id: string
  principal: string
  scope: string
  status: 'active' | 'revoked'
  revoked_at: string | null
  revoked_reason: string | null
}

export interface HoldRow {
  hold_id: string
  entity_type: string
  entity_id: string
  reason: string
  placed_by: string
  placed_at: string
  active: boolean
}

export interface IncidentInfo {
  incident_id: string
  title: string
  description: string
  started_at: string
  detected_at: string
  tenant_id: string
  other_tenants_affected?: boolean
  affected?: { tenant_id: string; order_id: string; damage?: string }[]
}

export interface AnnotationRow {
  annotation_id: string
  author: string
  created_at: string
  body: string
  trust: 'untrusted'
}

/** Whether the disposable demo data has already been repaired in this generation. */
export interface FixtureStatus {
  generation?: number
  dirty: boolean
  repaired_orders: string[]
  note?: string | null
}

export interface AppState {
  tenant: { id: string; name: string }
  orders: OrderRow[]
  deleted: DeletedEntity[]
  access_grants: AccessGrantRow[]
  holds: HoldRow[]
  snapshot: {
    snapshot_id: string
    taken_at: string
    content_digest: string
    approved_by: string | null
    approved_at?: string | null
    description?: string
    annotations?: AnnotationRow[]
  }
  incident: IncidentInfo
  beacon: {
    checksum: string
    expected_checksum: string
    untouched: boolean
    order_count: number
  }
  fixture_generation: number
  fixture?: FixtureStatus
}

export interface SnapshotOrderValues {
  status: string
  total_cents: number
  shipping_region: string | null
}

export interface SnapshotDiffRow {
  order_id: string
  customer_name: string
  condition: OrderCondition
  snapshot: SnapshotOrderValues
  current: SnapshotOrderValues | null
  differing_fields: string[]
  customer_id?: string
  notes?: string
}

export interface ProposalBundle {
  proposal: ActionProposal
  decisions: Decision[]
  manifest?: ExecutionManifest | null
  receipt?: ExecutionReceipt | null
  approval?: ApprovalRecord | null
}

export interface LatencySummary {
  p50: number | null
  p95: number | null
  count: number
  by_source?: Record<string, LatencySummary>
}

export interface RunMetrics {
  proposals: number
  executed: number
  blocked_by_layer: Partial<Record<Layer, number>>
  forbidden_effects_observed: number
  prohibited_handler_entries: number
  replans: number
  commits: number
  armoriq_latency_ms: LatencySummary
  end_to_end_ms: number | null
}

export interface RunDetail {
  run: Run
  grant: TaskGrant
  proposals: ProposalBundle[]
  approvals: ApprovalRecord[]
  receipts: ExecutionReceipt[]
  metrics: RunMetrics
  protected_checks: InvariantCheck[]
}

/** GET /metrics: aggregate across runs (server shape; fields beyond RunMetrics are optional). */
export interface Metrics extends Partial<RunMetrics> {
  runs?: number
  blocked_proposals?: number
  protected_checks_violated?: number
  enforcement_unavailable?: number
  run_status?: Record<string, number>
  enforcement_modes?: Record<string, number>
  /** ArmorIQ latency split by what was timed (contract C7). */
  armoriq?: {
    plan_binding?: { count: number }
    enforce?: Partial<LatencySummary>
    issuance?: Partial<LatencySummary>
  }
  simulated?: boolean
  /** Legacy names, kept optional for older servers. */
  forbidden_proposals?: number
  safe_replans?: number
  [key: string]: unknown
}

/** POST /grants/draft response may carry the demo-data status so the UI can offer "Reset & run". */
export type GrantDraft = TaskGrant & { fixture?: FixtureStatus }

/** GET /evidence/live: recorded real-service evidence plus the current readiness probe. */
export interface GateAProbe {
  probe?: string
  name?: string
  outcome?: string
  source?: string
  latency_ms?: number | null
  matched_policy?: string | null
  detail?: string | null
  [key: string]: unknown
}

export interface GateAEvidence {
  created_at?: string
  date?: string
  sdk_version?: string | null
  plan_hash?: string | null
  probes?: GateAProbe[]
  [key: string]: unknown
}

export interface InjectionEvalModel {
  model: string
  trials: number
  attempted_restore: number
  attempted_cross_tenant: number
  examples?: unknown[]
}

export interface InjectionEvalBriefing {
  briefing: 'task_only' | 'with_rules' | string
  label: string
  models: InjectionEvalModel[]
}

export interface InjectionEval {
  created_at?: string
  note?: string
  with_enforcement?: boolean
  headline_briefing?: string
  /** Headline briefing's results (kept for older readers). */
  models: InjectionEvalModel[]
  /** Same models evaluated under each briefing (task only vs task plus the grant's rules). */
  briefings?: InjectionEvalBriefing[]
}

export interface LiveEvidence {
  gate_a: GateAEvidence | null
  gate_a_early: string | null
  injection_eval: InjectionEval | null
  readiness: EnforcementReadiness | null
}

export interface VerificationResult {
  check_id: string
  title: string
  guarantee: string
  layer_expected: Layer | string
  layer_actual: Layer | string | null
  group?: string
  source_actual?: string | null
  error?: string
  passed: boolean
  evidence: Record<string, unknown>
  duration_ms: number
}

export type VerificationStatus = 'running' | 'passed' | 'failed' | 'blocked'

export interface VerificationRun {
  verification_id: string
  status: VerificationStatus
  started_at?: string
  finished_at?: string | null
  enforcement_mode?: 'live' | 'offline'
  results: VerificationResult[]
  summary: Record<string, unknown>
}

export type RunPlannerChoice = 'auto' | 'scripted' | 'llm'

export interface ApiErrorBody {
  error: { code: string; message: string }
}
