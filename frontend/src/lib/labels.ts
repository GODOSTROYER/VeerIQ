import {
  CalendarClock,
  KeyRound,
  Lock,
  Package,
  PauseCircle,
  RotateCcw,
  Trash2,
  type LucideIcon,
} from 'lucide-react'
import type {
  ApprovalStatus,
  GrantStatus,
  InvariantCategory,
  InvariantStatus,
  OrderCondition,
  ProposalStatus,
  RunStatus,
  ScenarioKind,
  SystemWarning,
  ToolKind,
} from '@/api/types'
import { titleCase } from './format'

/** One place that turns backend vocabulary into words a person would use. */

export const TOOL_LABELS: Record<string, { label: string; summary: string; kind: ToolKind }> = {
  inspect_snapshot: { label: 'Inspect snapshot', summary: 'Read the approved snapshot for this incident', kind: 'read' },
  compare_current: { label: 'Compare with current data', summary: 'Check each order against what is true today', kind: 'read' },
  prepare_repair_manifest: { label: 'Prepare repair', summary: 'Draft the exact changes, using values from the snapshot only', kind: 'prepare' },
  apply_repair_manifest: { label: 'Apply repair', summary: 'Commit the prepared repair in one transaction', kind: 'mutate' },
  get_recovery_receipt: { label: 'Get receipt', summary: 'Fetch the signed record of what changed', kind: 'read' },
  restore_access_grant: { label: 'Restore access grant', summary: 'Re-enable a revoked service account', kind: 'admin' },
}

export function toolLabel(name: string): string {
  return TOOL_LABELS[name]?.label ?? titleCase(name)
}

export function toolSummary(name: string): string {
  return TOOL_LABELS[name]?.summary ?? ''
}

export const FIELD_LABELS: Record<string, string> = {
  total_cents: 'Order total',
  shipping_region: 'Shipping region',
  status: 'Order status',
  owner_account: 'Account owner',
  customer_id: 'Customer',
}
export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? titleCase(field)
}

export const RESOURCE_LABELS: Record<string, { one: string; many: string }> = {
  order: { one: 'order', many: 'orders' },
  snapshot: { one: 'snapshot', many: 'snapshots' },
  customer: { one: 'customer', many: 'customers' },
}
export function resourceLabel(kind: string, count = 2): string {
  const r = RESOURCE_LABELS[kind]
  return r ? (count === 1 ? r.one : r.many) : titleCase(kind)
}

export const TENANT_NAMES: Record<string, string> = { atlas: 'Atlas Outfitters', beacon: 'Beacon Coffee Co.' }
export function tenantName(id: string): string {
  return TENANT_NAMES[id] ?? titleCase(id)
}

export const RUN_STATUS: Record<RunStatus, { label: string; tone: Tone; live: boolean }> = {
  created: { label: 'Created', tone: 'neutral', live: true },
  authorized: { label: 'Authorized', tone: 'neutral', live: true },
  planning: { label: 'Agent working', tone: 'info', live: true },
  awaiting_approval: { label: 'Waiting for reviewer', tone: 'hold', live: true },
  executing: { label: 'Agent working', tone: 'info', live: true },
  succeeded: { label: 'Repaired', tone: 'good', live: false },
  partially_succeeded: { label: 'Partly repaired', tone: 'hold', live: false },
  blocked: { label: 'Stopped', tone: 'bad', live: false },
  failed: { label: 'Failed', tone: 'bad', live: false },
  cancelled: { label: 'Cancelled', tone: 'neutral', live: false },
}

export const PROPOSAL_STATUS: Record<ProposalStatus, { label: string; tone: Tone }> = {
  pending: { label: 'Checking', tone: 'info' },
  executed: { label: 'Done', tone: 'good' },
  blocked: { label: 'Blocked', tone: 'bad' },
  held: { label: 'Waiting for reviewer', tone: 'hold' },
  rejected: { label: 'Rejected', tone: 'bad' },
  stale: { label: 'Out of date', tone: 'hold' },
  failed: { label: 'Failed', tone: 'bad' },
  unavailable: { label: 'Enforcement unavailable', tone: 'warn' },
  duplicate: { label: 'Replay, no change', tone: 'neutral' },
}

export const APPROVAL_STATUS: Record<ApprovalStatus, { label: string; tone: Tone }> = {
  pending: { label: 'Waiting', tone: 'hold' },
  approved: { label: 'Approved', tone: 'good' },
  rejected: { label: 'Rejected', tone: 'bad' },
  timed_out: { label: 'Timed out', tone: 'neutral' },
  expired: { label: 'Expired', tone: 'neutral' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
}

export const GRANT_STATUS: Record<GrantStatus, string> = {
  draft: 'Awaiting your approval',
  active: 'Active',
  exhausted: 'Used up',
  expired: 'Expired',
  revoked: 'Revoked',
}

export const INVARIANT_STATUS: Record<InvariantStatus, { label: string; tone: Tone }> = {
  preserved: { label: 'Preserved', tone: 'good' },
  repaired: { label: 'Repaired', tone: 'good' },
  pending: { label: 'Not yet repaired', tone: 'hold' },
  violated: { label: 'Violated', tone: 'bad' },
}

export const INVARIANT_CATEGORY: Record<InvariantCategory, { label: string; icon: LucideIcon }> = {
  repair: { label: 'Repair', icon: RotateCcw },
  tombstone: { label: 'Deletion', icon: Trash2 },
  access: { label: 'Access', icon: KeyRound },
  later_update: { label: 'Later update', icon: CalendarClock },
  tenant_isolation: { label: 'Other tenant', icon: Lock },
  hold: { label: 'Hold', icon: PauseCircle },
}

export const CONDITION: Record<OrderCondition, { label: string; tone: Tone; icon: LucideIcon }> = {
  damaged: { label: 'Damaged', tone: 'bad', icon: Package },
  healthy: { label: 'Healthy', tone: 'good', icon: Package },
  changed_after_snapshot: { label: 'Later update kept', tone: 'info', icon: CalendarClock },
  deleted_tombstoned: { label: 'Deleted stays deleted', tone: 'neutral', icon: Trash2 },
  on_hold: { label: 'On hold', tone: 'hold', icon: PauseCircle },
}

export const SCENARIO_KIND: Record<ScenarioKind, string> = {
  flagship: 'Flagship',
  baseline: 'Baseline',
  race: 'Race condition',
  approval: 'Second reviewer',
  boundary: 'Boundary test',
}

export const PLANNER_CHOICES = {
  auto: { label: 'Auto', hint: 'Use the scenario default' },
  scripted: { label: 'Scripted', hint: 'Deterministic, no LLM' },
  llm: { label: 'Live LLM', hint: 'A language model plans the steps' },
} as const

export const PROVIDER_LABEL: Record<string, string> = { groq: 'Groq', anthropic: 'Anthropic', openai: 'OpenAI' }

export function providerLabel(provider: string | null | undefined): string {
  if (!provider) return ''
  return PROVIDER_LABEL[provider.toLowerCase()] ?? titleCase(provider)
}

/** "openai/gpt-oss-120b" is a Groq-hosted model name, so strip the vendor prefix for display. */
function shortModel(model: string): string {
  return model.replace(/^[a-z0-9-]+\//i, '')
}

/** Splits "<provider>:<model>" (the model may itself contain ":" or "/"). */
export function splitPlanner(planner: string): { provider: string; model: string } | null {
  const i = planner.indexOf(':')
  if (i <= 0) return null
  return { provider: planner.slice(0, i), model: planner.slice(i + 1) }
}

/**
 * Human label for a planner. Prefer the server's own label (run.metadata.planner_label) when given.
 * Examples: "Groq gpt-oss-120b", "Scripted agent (no LLM)".
 */
export function plannerLabel(planner: string, kind: 'scripted' | 'llm' | 'harness', serverLabel?: string | null): string {
  if (serverLabel) return serverLabel
  if (kind === 'scripted') return 'Scripted agent (no LLM)'
  if (kind === 'harness') return 'Boundary harness'
  const parts = splitPlanner(planner)
  return parts ? `${providerLabel(parts.provider)} ${shortModel(parts.model)}` : titleCase(planner)
}

/** Short badge text: says plainly whether a real model or a scripted re-enactment drove the run. */
export function plannerBadgeText(planner: string, kind: 'scripted' | 'llm' | 'harness', serverLabel?: string | null): string {
  if (kind === 'llm') return serverLabel ?? `Live LLM: ${plannerLabel(planner, kind)}`
  if (kind === 'harness') return serverLabel ?? 'Boundary harness'
  return serverLabel ?? 'Scripted re-enactment'
}

/** Accepts both the legacy string[] and the object form so older servers keep working. */
export function normaliseWarnings(warnings: (SystemWarning | string)[] | undefined): SystemWarning[] {
  return (warnings ?? []).map((w) =>
    typeof w === 'string'
      ? { level: /unreachable|unavailable|simulated/i.test(w) ? 'warn' : 'info', code: w.slice(0, 40), message: w }
      : w,
  )
}

export type Tone = 'neutral' | 'good' | 'bad' | 'hold' | 'info' | 'warn'

/** Token reference for a tone. */
export const TONE_COLOR: Record<Tone, string> = {
  neutral: 'var(--outcome-neutral)',
  good: 'var(--outcome-allow)',
  bad: 'var(--outcome-block)',
  hold: 'var(--outcome-hold)',
  info: 'var(--outcome-info)',
  warn: 'var(--outcome-unavailable)',
}

/** Plain-language names for machine invariant ids (shown in technical details only, beside the raw id). */
export const INVARIANT_LABELS: Record<string, string> = {
  tool_not_granted: 'Tool not in the grant',
  tenant_scope: 'Another tenant\u2019s data',
  resource_scope: 'Record outside the grant',
  snapshot_scope: 'Different snapshot',
  field_scope: 'Field outside the grant',
  manifest_scope: 'Repair belongs to another grant',
  snapshot_value: 'Value not from the snapshot',
  tombstone: 'Deleted record',
  later_update: 'Newer legitimate edit',
  record_hold: 'Record on hold',
  manifest_digest: 'Repair was altered',
  generation: 'Outdated demo data',
  idempotency_conflict: 'Key reused with a different repair',
  no_authority_expansion: 'Grant cannot be widened',
  step_budget: 'Step budget used up',
  stale_state: 'State changed since preview',
}
export function invariantLabel(id: string | null | undefined): string {
  if (!id) return ''
  return INVARIANT_LABELS[id] ?? titleCase(id)
}
