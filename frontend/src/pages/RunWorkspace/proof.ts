import type { InvariantCheck, Layer, Run, RunMetrics, TaskGrant } from '@/api/types'
import { truncateDigest } from '@/lib/format'
import { invariantLabel, toolLabel, type Tone } from '@/lib/labels'
import { isSimulatedEnforcement, type EnforcementFacts } from '@/lib/layers'
import { blockerPhrase, rec, str, times, joinList, type RunView } from './model'

export interface ProofLine {
  tone: Tone
  text: string
  /** Supporting measurements and fingerprints, revealed by Technical. */
  technicalText?: string
}

export interface UnrepairedOrder {
  orderId: string
  reason: string
}

export interface RecordedProtectedEvidence {
  checks: InvariantCheck[]
  source: 'run_finished' | 'receipt'
  observedAt?: string
}

/** Historical protected-state evidence, never inferred from the live tenant state. */
export function recordedProtectedChecks(view: RunView): RecordedProtectedEvidence | undefined {
  const finishData = rec(view.finish?.data)
  const finishChecks = finishData.protected_checks
  const direct = Array.isArray(finishChecks) ? finishChecks : rec(finishChecks).checks
  if (Array.isArray(direct)) {
    const observation = rec(finishData.protected_check_observation)
    return {
      checks: direct as InvariantCheck[],
      source: 'run_finished',
      observedAt: typeof observation.observed_at === 'string' ? observation.observed_at : undefined,
    }
  }

  const receipt = view.receipts.filter(r => r.result === 'committed').at(-1)
  return receipt?.checks.length ? { checks: receipt.checks, source: 'receipt', observedAt: receipt.committed_at ?? undefined } : undefined
}

const ACTION_VERB: Record<string, string> = {
  place_hold: 'placed a hold on',
  add_tombstone: 'recorded a deletion of',
  revoke_access: 'revoked access for',
}

/** "Finance (dispute desk) placed a hold on O-2042". Built from the event's own fields. */
export function externalSentence(data: Record<string, unknown>, fallbackTitle: string): string {
  const who = str(data.actor_label)
  const verb = ACTION_VERB[str(data.action) ?? '']
  const target = str(data.target)
  if (who && verb && target) return `${who} ${verb} ${target}`
  return fallbackTitle
}

/** Granted orders that were not repaired, each with the recorded reason. */
export function unrepairedOrders(grant: TaskGrant | undefined, view: RunView): UnrepairedOrder[] {
  if (!grant) return []
  const wanted = [...(grant.resources.order ?? []), ...(grant.reviewable.order ?? [])]
  const out: UnrepairedOrder[] = []
  for (const orderId of wanted) {
    if (view.committedOrderIds.includes(orderId)) continue
    const ext = view.externals.find((e) => str(rec(e.data).target) === orderId)
    if (ext) {
      const d = rec(ext.data)
      const reason = str(d.reason)
      out.push({
        orderId,
        reason: `${externalSentence(d, ext.title)}${reason ? ` (${reason})` : ''} after the repair was previewed, so the repair was not applied to it.`,
      })
      continue
    }
    const rej = view.rejections.find((e) => e.detail.includes(orderId) || e.title.includes(orderId))
    if (rej) {
      out.push({ orderId, reason: rej.detail || rej.title })
      continue
    }
    out.push({ orderId, reason: 'No repair was committed for it during this run.' })
  }
  return out
}

interface ProofInput {
  view: RunView
  run: Run | undefined
  grant: TaskGrant | undefined
  checks: InvariantCheck[] | undefined
  metrics: RunMetrics | undefined
  live: boolean
  nameOf: (identityId: string | null | undefined) => string
  enforcement: EnforcementFacts
  generationMismatch?: boolean
}

/**
 * Plain-English statements derived only from recorded events, decisions and checks.
 * Nothing here is asserted unless the data to back it is present.
 */
export function buildProof({ view, run, grant, checks: currentChecks, metrics, live, nameOf, enforcement, generationMismatch = false }: ProofInput): ProofLine[] {
  const lines: ProofLine[] = []
  const historicalChecks = recordedProtectedChecks(view)
  const checks = historicalChecks?.checks ?? (live && !generationMismatch ? currentChecks : undefined)

  // 1. Every tool that was stopped, grouped.
  const tools: string[] = []
  for (const p of view.proposals) if (p.status === 'blocked' && !tools.includes(p.tool)) tools.push(p.tool)
  for (const tool of tools) {
    const attempts = view.proposals.filter((p) => p.tool === tool)
    const blocked = attempts.filter((p) => p.status === 'blocked')
    const by = Array.from(new Set(blocked.map((p) => (p.blocker ? blockerPhrase(p.blocker) : 'a protection layer'))))
    const invariants = Array.from(new Set(blocked.map((p) => p.blocker?.invariant).filter((x): x is string => !!x))).map(invariantLabel)
    const all = blocked.length === attempts.length
    let text = `“${toolLabel(tool)}” was attempted ${times(attempts.length)}${
      all ? ' and blocked every time' : `; ${blocked.length} of those ${blocked.length === 1 ? 'was' : 'were'} blocked`
    } by ${joinList(by, 3)}${invariants.length ? ` (${invariants.join(', ')})` : ''}.`
    text += ' Nothing was changed by the blocked attempt.'
    const access = tool === 'restore_access_grant' ? checks?.find((c) => c.category === 'access') : undefined
    if (access && access.status === 'preserved') text += ` The protected check “${access.label}” still holds.`
    lines.push({ tone: 'good', text, technicalText: tool === 'restore_access_grant' && metrics ? `Its handler was entered ${times(metrics.prohibited_handler_entries)}.` : undefined })
  }

  // 2. Commits.
  for (const r of view.receipts) {
    if (r.result !== 'committed') continue
    const orders = Array.from(new Set(r.changes.map((c) => c.row_id)))
    const rows = r.effect_counts.rows_updated ?? orders.length
    lines.push({
      tone: 'good',
      text: `One repair was committed in a single transaction: ${rows} ${rows === 1 ? 'row' : 'rows'} updated (${joinList(orders, 6)}).`,
      technicalText: `Receipt digest: ${truncateDigest(r.receipt_digest)}.`,
    })
  }

  // 3. Rejections before any write.
  for (const e of view.rejections) {
    lines.push({
      tone: 'hold',
      text: `A repair was rejected before it wrote anything: ${e.detail || e.title}`,
    })
  }

  // 4. Approvals.
  for (const a of view.approvals) {
    if (a.status === 'approved') {
      lines.push({ tone: 'good', text: `${nameOf(a.decided_by)} approved the exact change before it ran.`, technicalText: `Approved payload digest: ${truncateDigest(a.payload_digest)}.` })
    } else if (a.status === 'rejected') {
      lines.push({ tone: 'good', text: `${nameOf(a.decided_by)} rejected the payload, so nothing changed.` })
    } else if (a.status === 'timed_out' || a.status === 'expired') {
      lines.push({ tone: 'hold', text: 'The reviewer did not decide in time, so the action did not run.' })
    }
  }

  // 5. Enforcement could not be reached.
  const unavailable = view.proposals.filter((p) => p.status === 'unavailable')
  if (unavailable.length) {
    lines.push({
      tone: 'warn',
      text: `Enforcement could not be reached for ${unavailable.length} ${unavailable.length === 1 ? 'action' : 'actions'}. They failed closed and did not run. This was not a policy denial.`,
    })
  }

  // 6. Protected state.
  if (checks) {
    const guarded = checks.filter((c) => c.category !== 'repair')
    const violated = guarded.filter((c) => c.status === 'violated')
    if (violated.length) {
      lines.push({ tone: 'bad', text: `Protected state was violated: ${violated.map((c) => c.label).join('; ')}.` })
    } else if (guarded.length && guarded.every(isHeld)) {
      lines.push({
        tone: 'good',
        text: `All ${guarded.length} protected-state checks ${historicalChecks ? `were recorded as preserved at ${historicalChecks.source === 'receipt' ? 'commit' : 'run completion'}` : 'hold right now'}: ${joinList(guarded.map((c) => c.label.charAt(0).toLowerCase() + c.label.slice(1)), 6)}.`,
      })
    } else if (guarded.length) {
      lines.push({ tone: 'neutral', text: `${guarded.filter(isHeld).length} of ${guarded.length} protected-state checks hold; the remaining checks are not yet confirmed.` })
    }
  }

  // 7. Partial repairs.
  if (run?.status === 'partially_succeeded') {
    for (const u of unrepairedOrders(grant, view)) lines.push({ tone: 'hold', text: `${u.orderId} was not repaired: ${u.reason}` })
  }

  // 8. Honest disclosure of what ArmorIQ did.
  if (run && isSimulatedEnforcement(enforcement)) {
    lines.push({
      tone: 'hold',
      text: 'Enforcement was simulated for this run. Decisions labelled ArmorIQ come from a local simulation, not the live ArmorIQ service. Grant, domain and PostgreSQL checks were real.',
    })
  }
  if (live) {
    lines.push({ tone: 'neutral', text: 'This run is still in progress. These statements update as events arrive.' })
  }
  if (!live && !historicalChecks) {
    lines.push({ tone: 'neutral', text: 'Detailed historical protected checks were not recorded for this run. Current data cannot certify the past.' })
  } else if (generationMismatch && !checks) {
    lines.push({ tone: 'neutral', text: 'The demo data was reset after this run. Today’s checks do not certify the older run; its recorded decisions remain available below.' })
  }
  if (lines.length === 0) {
    lines.push({ tone: 'neutral', text: 'Nothing has been decided yet. Statements appear here as the agent acts.' })
  }
  return lines
}

export function manifestOrderIds(manifest: { changes: Array<{ row_id: string }> }): string[] {
  return Array.from(new Set(manifest.changes.map((c) => c.row_id)))
}


/* ─── Certificate helpers ─── */

export interface StoppedGroup {
  tool: string
  attempts: number
  blocked: number
  /** Layers that blocked it, outermost first. */
  layers: Array<{ layer: Layer; simulated: boolean }>
  /** True when ArmorIQ stopped it. */
  armoriq: boolean
}

const LAYER_ORDER: Layer[] = ['armoriq', 'grant', 'domain', 'approval', 'postgres', 'runtime']

/** One entry per tool that was blocked at least once. */
export function stoppedGroups(view: RunView): StoppedGroup[] {
  const tools: string[] = []
  for (const p of view.proposals) if (p.status === 'blocked' && !tools.includes(p.tool)) tools.push(p.tool)
  return tools.map((tool) => {
    const attempts = view.proposals.filter((p) => p.tool === tool)
    const blocked = attempts.filter((p) => p.status === 'blocked')
    const seen = new Map<Layer, boolean>()
    for (const p of blocked) {
      // Every non-shadow block counts; a shadow block that agrees is shown on the card, not counted here.
      for (const d of p.decisions) if (d.outcome === 'block' && !d.shadow && !seen.has(d.layer)) seen.set(d.layer, d.simulated)
      if (p.blocker && !seen.has(p.blocker.layer)) seen.set(p.blocker.layer, p.blocker.simulated)
    }
    const layers = LAYER_ORDER.filter((l) => seen.has(l)).map((layer) => ({ layer, simulated: seen.get(layer) === true }))
    return { tool, attempts: attempts.length, blocked: blocked.length, layers, armoriq: layers.some((l) => l.layer === 'armoriq') }
  })
}

export interface RepairedOrder {
  orderId: string
  /** Dollars restored in cents when the order total changed; undefined when no total changed. */
  restoredCents: number | undefined
}

/** Orders committed in this run, with the recorded total restored from the receipts. */
export function repairedOrders(view: RunView): RepairedOrder[] {
  const byOrder = new Map<string, number | undefined>()
  for (const r of view.receipts) {
    if (r.result !== 'committed') continue
    for (const c of r.changes) {
      if (!byOrder.has(c.row_id)) byOrder.set(c.row_id, undefined)
      if (c.field === 'total_cents' && typeof c.before === 'number' && typeof c.after === 'number') {
        byOrder.set(c.row_id, (byOrder.get(c.row_id) ?? 0) + (c.after - c.before))
      }
    }
  }
  return Array.from(byOrder, ([orderId, restoredCents]) => ({ orderId, restoredCents }))
}

/** Orders the grant targets (directly or through review). */
export function targetOrders(grant: TaskGrant | undefined): string[] {
  if (!grant) return []
  return Array.from(new Set([...(grant.resources.order ?? []), ...(grant.reviewable.order ?? [])]))
}

/** Checks that guard today's decisions: everything except the repair itself and the other tenant. */
export function decisionChecks(checks: InvariantCheck[] | undefined): InvariantCheck[] {
  return (checks ?? []).filter((c) => c.category !== 'repair' && c.category !== 'tenant_isolation')
}

export function isHeld(c: InvariantCheck): boolean {
  return c.status === 'preserved' || c.status === 'repaired'
}
