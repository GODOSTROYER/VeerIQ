import {
  Ban,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Cog,
  Crosshair,
  Database,
  FlaskConical,
  Hourglass,
  PlugZap,
  Scale,
  ShieldCheck,
  TriangleAlert,
  UserCheck,
  type LucideIcon,
} from 'lucide-react'
import type { Decision, DecisionSource, Layer, Outcome } from '@/api/types'

export interface LayerMeta {
  label: string
  short: string
  /** CSS colour value (a token reference). Use with color-mix for tints. */
  color: string
  icon: LucideIcon
  description: string
}

/** Outermost to innermost. Runtime is shown separately: it is plumbing, not a defense tier. */
export const DEFENSE_LAYERS: readonly Layer[] = ['armoriq', 'grant', 'domain', 'approval', 'postgres']

export const LAYERS: Record<Layer, LayerMeta> = {
  armoriq: {
    label: 'ArmorIQ',
    short: 'ArmorIQ',
    color: 'var(--layer-armoriq)',
    icon: ShieldCheck,
    description:
      'ArmorIQ signs the task’s plan before the agent starts. Actions outside it are refused by the ArmorIQ SDK locally; in-plan actions are checked against ArmorIQ policy. Argument checks (tenant, records) are VeerIQ’s.',
  },
  grant: {
    label: 'Grant scope',
    short: 'Grant',
    color: 'var(--layer-grant)',
    icon: Crosshair,
    description: 'VeerIQ checks tenant, records, fields and snapshot against the grant a human reviewed.',
  },
  domain: {
    label: 'Domain invariant',
    short: 'Domain',
    color: 'var(--layer-domain)',
    icon: Scale,
    description: 'VeerIQ checks the data rules: snapshot values only, deletions stay deleted, no overwriting newer edits.',
  },
  approval: {
    label: 'Second reviewer',
    short: 'Approval',
    color: 'var(--layer-approval)',
    icon: UserCheck,
    description: 'A different person approves the exact payload before high-value changes can run.',
  },
  postgres: {
    label: 'PostgreSQL',
    short: 'Postgres',
    color: 'var(--layer-postgres)',
    icon: Database,
    description: 'The database itself refuses writes outside the executor role and re-checks state inside one transaction.',
  },
  runtime: {
    label: 'Runtime',
    short: 'Runtime',
    color: 'var(--layer-runtime)',
    icon: Cog,
    description: 'Tool registry, argument validation, step budget and grant lifecycle.',
  },
}

export interface SourceMeta {
  label: string
  short: string
  layer: Layer
  color: string
  icon: LucideIcon
  description: string
  /** True for ArmorIQ-sponsored sources (a VeerIQ decision must never carry this). */
  armoriq: boolean
}

function src(layer: Layer, label: string, short: string, description: string, armoriq = false, icon?: LucideIcon): SourceMeta {
  return { layer, label, short, color: LAYERS[layer].color, icon: icon ?? LAYERS[layer].icon, description, armoriq }
}

export const DECISION_SOURCES: Record<DecisionSource, SourceMeta> = {
  'armoriq.sdk.plan_binding': src(
    'armoriq',
    'ArmorIQ - signed plan',
    'Signed plan',
    'The ArmorIQ SDK compared the action with the plan ArmorIQ signed. Anything outside the plan is stopped before it reaches a handler.',
    true,
  ),
  'armoriq.backend.enforce': src(
    'armoriq',
    'ArmorIQ - policy',
    'Policy',
    'ArmorIQ evaluated this action against organization policy on its enforcement service.',
    true,
  ),
  'armoriq.backend.token_issuance': src(
    'armoriq',
    'ArmorIQ - plan issuance',
    'Plan issuance',
    'ArmorIQ decided whether it would sign a plan containing these tools.',
    true,
  ),
  'armoriq.backend.approval': src(
    'armoriq',
    'ArmorIQ - delegation',
    'Delegation',
    'ArmorIQ delegation approval status for a held action.',
    true,
  ),
  'armoriq.offline_simulation': src(
    'armoriq',
    'ArmorIQ (simulated)',
    'Simulated',
    'A deterministic local simulation that mirrors ArmorIQ semantics. This is not a decision from the live ArmorIQ service.',
    true,
    FlaskConical,
  ),
  'rewindsafe.grant_scope': src(
    'grant',
    'Grant scope',
    'Grant scope',
    'VeerIQ compared the request with the reviewed task grant.',
  ),
  'rewindsafe.domain': src(
    'domain',
    'Domain invariant',
    'Domain',
    'VeerIQ checked a data rule that protects today’s decisions.',
  ),
  'rewindsafe.approval': src(
    'approval',
    'Second reviewer',
    'Reviewer',
    'A human second reviewer decided on the exact payload.',
  ),
  'rewindsafe.tool_registry': src(
    'runtime',
    'Tool registry',
    'Registry',
    'VeerIQ validated the tool name and its arguments.',
  ),
  'rewindsafe.lifecycle': src(
    'runtime',
    'Grant lifecycle',
    'Lifecycle',
    'VeerIQ checked that the grant is active, unexpired and within its budget.',
  ),
  'postgres.privilege': src(
    'postgres',
    'PostgreSQL privilege',
    'DB privilege',
    'PostgreSQL refused the write because the executor role has no privilege on it.',
  ),
  'postgres.transaction': src(
    'postgres',
    'PostgreSQL transaction',
    'DB transaction',
    'The commit re-checked live state inside one database transaction.',
  ),
}

export interface OutcomeMeta {
  label: string
  /** Past-tense verb for sentences: "ArmorIQ blocked ...". */
  verb: string
  color: string
  icon: LucideIcon
  description: string
}

export const OUTCOMES: Record<Outcome, OutcomeMeta> = {
  allow: { label: 'Allowed', verb: 'allowed', color: 'var(--outcome-allow)', icon: CheckCircle2, description: 'This layer let the action through.' },
  block: { label: 'Blocked', verb: 'blocked', color: 'var(--outcome-block)', icon: Ban, description: 'This layer stopped the action. Nothing changed.' },
  hold: { label: 'Held for review', verb: 'held', color: 'var(--outcome-hold)', icon: Hourglass, description: 'The action waits for a second reviewer.' },
  unavailable: {
    label: 'Enforcement unavailable',
    verb: 'could not be checked',
    color: 'var(--outcome-unavailable)',
    icon: PlugZap,
    description: 'The enforcement service could not be reached, so the action failed closed. This is not a policy denial.',
  },
  error: { label: 'Error', verb: 'errored', color: 'var(--outcome-unavailable)', icon: TriangleAlert, description: 'The layer hit an error.' },
  skipped: { label: 'Skipped', verb: 'skipped', color: 'var(--outcome-neutral)', icon: CircleDashed, description: 'Not evaluated for this action.' },
}

export const PENDING_ICON = Clock3

/** Layer for a source, derived from the source map (never from the decision's own claim). */
export function layerOfSource(source: DecisionSource): Layer {
  return DECISION_SOURCES[source]?.layer ?? 'runtime'
}

/** Source label that is honest about simulation. */
export function sourceLabel(decision: Pick<Decision, 'source' | 'simulated'>): string {
  const meta = DECISION_SOURCES[decision.source]
  if (!meta) return decision.source
  if (decision.simulated && !meta.label.includes('simulated')) return `${meta.label} (simulated)`
  return meta.label
}

/** Copy for a decision's headline, e.g. "ArmorIQ - policy blocked this action". */
export function decisionHeadline(d: Decision): string {
  const who = sourceLabel(d)
  const verb = OUTCOMES[d.outcome]?.verb ?? d.outcome
  if (d.shadow) return `${who} would also have ${d.outcome === 'allow' ? 'allowed' : verb} this`
  return `${who} ${verb} this action`
}

/** Facts about where a run's ArmorIQ decisions came from. Pass whatever is known; every field is optional. */
export interface EnforcementFacts {
  enforcement_mode?: string | null
  plan?: { mode?: string | null; simulated?: boolean | null } | null
  decisions?: ReadonlyArray<{ simulated?: boolean | null }> | null
}

/**
 * The one rule for calling ArmorIQ enforcement "simulated". Every "Live" or "Simulated" label in the
 * run workspace comes from this, so one run can never read live in one place and simulated in another.
 * Simulated unless the configured mode is live. A plan or decision that is present but not positively live
 * (its mode or simulated flag does not say so) also makes it simulated. Absent facts do not: a missing plan
 * or an empty decision list is not evidence of simulation.
 */
export function isSimulatedEnforcement(facts: EnforcementFacts): boolean {
  if (facts.enforcement_mode !== 'live') return true
  if (facts.plan && (facts.plan.mode !== 'live' || facts.plan.simulated !== false)) return true
  return (facts.decisions ?? []).some((d) => d.simulated !== false)
}
