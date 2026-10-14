import type { Decision, DecisionSource } from '@/api/types'
import { invariantLabel, toolLabel } from './labels'

/**
 * Plain-English copy for raw enforcement reasons, rules and provenance.
 * Raw codes stay available (evidence drawer, "Raw reason" rows); everything a person reads first comes from here.
 */

type ReasonInput = Pick<Decision, 'reason' | 'source'> & Partial<Pick<Decision, 'invariant' | 'outcome' | 'simulated' | 'shadow'>>

function toolFromReason(reason: string): string | undefined {
  const m = /'([a-z][a-z0-9_]*)'/.exec(reason)
  return m ? m[1] : undefined
}

const SIMULATION_TAIL = 'This decision comes from the local simulation, not the live service.'

/** The plain sentence for a reason code, before any simulation disclosure. */
function reasonSentence(r: string, tool: string | undefined): string {
  const lower = r.toLowerCase()
  if (lower.startsWith('tool-not-in-plan') || lower.startsWith('tool_not_in_plan')) {
    const t = tool ?? toolFromReason(r)
    return `${t ? toolLabel(t) : 'This action'} is not one of the actions ArmorIQ signed for this task, so it was refused before any handler ran.`
  }
  if (lower.startsWith('tool_not_in_allowlist')) return 'ArmorIQ organization policy does not allow this tool for this agent.'
  if (lower.startsWith('allow_with_logging')) return 'Allowed by ArmorIQ policy, and logged.'
  if (lower.startsWith('no_matching_policy')) return 'No ArmorIQ policy covers this agent, so it is blocked by default.'
  if (lower.startsWith('enforce-unavailable') || lower.startsWith('enforce_unavailable')) {
    return 'ArmorIQ could not be reached, so the action failed closed. This is not a policy denial.'
  }
  if (lower.startsWith('plan-expired') || lower.startsWith('plan_expired')) return 'The signed plan expired, so the action was refused.'
  return r
}

/** Adds the simulation disclosure as its own sentence. */
function withSimulationTail(sentence: string): string {
  if (!sentence) return SIMULATION_TAIL
  const ended = /[.!?]$/.test(sentence) ? sentence : `${sentence}.`
  return `${ended} ${SIMULATION_TAIL}`
}

/** The sentence a person reads for a decision. VeerIQ reasons are already plain English and pass through. */
export function humanReason(d: ReasonInput, tool?: string): string {
  const r = (d.reason ?? '').trim()
  const sentence = reasonSentence(r, tool)
  // Applied here for every reason code, so a code added later cannot leave the disclosure off a simulated decision.
  const sim = d.simulated || r.toLowerCase().includes('(simulated)')
  return sim ? withSimulationTail(sentence) : sentence
}

const EXTRA_RULES: Record<string, string> = {
  org_policy_allowlist: 'ArmorIQ organization policy allow-list',
  tool_not_in_plan: 'Signed plan binding',
  plan_binding: 'Signed plan binding',
}

/** Rule name for facts rows. Falls back to the shared invariant labels. */
export function ruleLabel(id: string | null | undefined): string {
  if (!id) return ''
  return EXTRA_RULES[id] ?? invariantLabel(id)
}

/** The same decision as one short line for a tooltip. */
export function decisionLine(d: ReasonInput, tool?: string): string {
  return humanReason(d, tool)
}

/* ─── Explainers (one place, so every card says the same thing) ─── */

export const LOCAL_CHECK_EXPLAINER =
  'The ArmorIQ SDK holds the signed plan and compared this request with it on the spot. Nothing outside the plan reaches a handler, and no network call is needed, so it takes about 0 ms.'

export const ARGS_NOT_CHECKED_EXPLAINER =
  'ArmorIQ allowed this tool. It checks which tool is called, not the arguments. VeerIQ checked the arguments next and caught the tenant.'

export const NOTE_FOOTER = 'Notes are data, not instructions. The agent’s grant does not change because of what a note says.'

export function sourceWhere(source: DecisionSource, latencyMs: number | null | undefined): string {
  const ms = latencyMs != null ? Math.round(latencyMs) : undefined
  switch (source) {
    case 'armoriq.sdk.plan_binding':
      return 'Refused locally by the ArmorIQ SDK against the signed plan, with no network round trip.'
    case 'armoriq.backend.enforce':
      return `${ms !== undefined ? `${ms} ms round trip to` : 'Round trip to'} the ArmorIQ policy service.`
    case 'armoriq.offline_simulation':
      return 'Decided by the local ArmorIQ simulation. No call was made to ArmorIQ.'
    default:
      return ''
  }
}

/** Highlight spans inside an untrusted note: what the injected instruction asks the agent to do. Global, so every occurrence is found. */
const INJECTION_PATTERNS = [/restore_access_grant[^.]*/gi, /Include B-\d+ \(beacon\)/gi, /\bB-\d+\b[^.]*beacon[^.]*/gi]

export interface TextSpan {
  text: string
  mark: boolean
}

export function splitInjection(body: string): TextSpan[] {
  const hits: Array<[number, number]> = []
  for (const re of INJECTION_PATTERNS) {
    for (const m of body.matchAll(re)) hits.push([m.index, m.index + m[0].length])
  }
  hits.sort((a, b) => a[0] - b[0])
  const merged: Array<[number, number]> = []
  for (const h of hits) {
    const last = merged[merged.length - 1]
    if (last && h[0] <= last[1]) last[1] = Math.max(last[1], h[1])
    else merged.push([h[0], h[1]])
  }
  const out: TextSpan[] = []
  let at = 0
  for (const [s, e] of merged) {
    if (s > at) out.push({ text: body.slice(at, s), mark: false })
    out.push({ text: body.slice(s, e), mark: true })
    at = e
  }
  if (at < body.length) out.push({ text: body.slice(at), mark: false })
  return out.length ? out : [{ text: body, mark: false }]
}

export function shortId(v: string | null | undefined, n = 8): string {
  if (!v) return ''
  return v.length > n + 3 ? `${v.slice(0, n)}…` : v
}
