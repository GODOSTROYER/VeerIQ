import type { Layer, RunStatus } from '@/api/types'
import { OUTCOMES } from '@/lib/layers'
import { type ProposalItem, type RunView } from './model'
import type { CardCtx } from './TimelineCards'

export const GATE_MEANING: Record<Layer, string> = {
  armoriq: 'Only actions in the plan signed before the agent started are allowed.',
  grant: 'Only the tenant, orders and fields a person allowed can be used.',
  domain: 'Snapshot values may be restored; deletions and newer decisions must survive.',
  approval: 'High-value changes need a different person to approve the exact repair.',
  postgres: 'The database checks the repair again before writing it in one transaction.',
  runtime: 'The request must be valid and the agent must still have permission to act.',
}

export function approvalFor(p: ProposalItem | undefined, view: RunView) {
  return view.approvals.find(a => a.proposal_id === p?.proposalId)
}

export function receiptFor(p: ProposalItem | undefined, view: RunView) {
  return p?.tool === 'apply_repair_manifest' ? view.receipts.find(r => r.result === 'committed' && r.manifest_id === p.args.manifest_id) : undefined
}

export function stopFor(p: ProposalItem | undefined, view: RunView): Layer | undefined {
  if (!p) return undefined
  if (p.blocker) return p.blocker.layer
  if (p.unavailable) return p.unavailable.layer
  const approval = approvalFor(p, view)
  if (p.status === 'held' || (approval && approval.status !== 'approved')) return 'approval'
  const refusal = [...p.decisions].reverse().find(d => !d.shadow && ['block', 'unavailable', 'error'].includes(d.outcome))
  if (refusal) return refusal.layer
  if (p.status === 'stale' || p.status === 'rejected') return 'postgres'
  if (p.status === 'failed') return 'runtime'
  return undefined
}

/** The next sequential check after the last recorded admission, never a fabricated pass. */
export function pendingGate(p: ProposalItem | undefined, view: RunView): Layer | undefined {
  if (!p || p.status !== 'pending' || stopFor(p, view)) return undefined
  const order: Layer[] = ['armoriq', 'grant', 'domain', 'approval', 'postgres']
  const last = Math.max(-1, ...p.decisions.filter(d => !d.shadow && d.outcome === 'allow').map(d => order.indexOf(d.layer)))
  return order[last + 1]
}

export function gateResult(id: Layer, p: ProposalItem | undefined, ctx: CardCtx): { label: string; inferred?: boolean; shadow?: boolean; pending?: boolean } {
  if (!p) return { label: 'Waiting' }
  const stop = stopFor(p, ctx.view)
  const order: Layer[] = ['runtime', 'armoriq', 'grant', 'domain', 'approval', 'postgres']
  const own = p.decisions.filter(d => d.layer === id)
  const actual = [...own].reverse().find(d => !d.shadow && d.outcome !== 'skipped')
  if (stop && order.indexOf(id) > order.indexOf(stop)) return { label: own.some(d => d.shadow && d.outcome === 'block') ? 'Would also block · not reached' : 'Not reached', shadow: own.some(d => d.shadow && d.outcome === 'block') }
  const checking = pendingGate(p, ctx.view)
  if (checking && !actual) {
    if (id === checking) return { label: 'Checking', pending: true }
    if (order.indexOf(id) > order.indexOf(checking)) return { label: 'Not reached yet' }
    if (id !== 'runtime') return { label: 'Passed', inferred: true }
  }
  const approval = approvalFor(p, ctx.view)
  const admitted = ['executed', 'held', 'stale', 'rejected', 'duplicate'].includes(p.status) || !!approval
  if (id === 'approval' && (admitted || stop === 'approval')) {
    return { label: approval?.status === 'approved' ? `Approved by ${ctx.nameOf(approval.decided_by)}` : approval?.status === 'pending' || p.status === 'held' ? 'Waiting for a second person' : approval?.status === 'timed_out' ? 'Timed out' : approval ? 'Rejected' : actual ? OUTCOMES[actual.outcome].label : 'Not needed' }
  }
  if (id === 'postgres') {
    if (actual && actual.outcome !== 'allow') return { label: OUTCOMES[actual.outcome].label }
    if (p.tool !== 'apply_repair_manifest' && admitted) return { label: 'Not involved' }
    if (receiptFor(p, ctx.view)) return { label: 'Committed' }
    if (stop === id) return { label: 'Rejected before write' }
    return { label: admitted ? 'No commit recorded' : 'Not reached' }
  }
  if (actual) return { label: actual.outcome === 'allow' ? 'Passed' : OUTCOMES[actual.outcome].label }
  // Admission is sequential. A later gate's refusal also proves earlier checks passed.
  if (admitted || (stop && order.indexOf(id) < order.indexOf(stop))) return { label: 'Passed', inferred: true }
  return { label: p.status === 'pending' ? 'Not reached yet' : 'Not reached' }
}

export function recordedVerification(view: RunView): boolean {
  const receipt = view.receipts.filter(r => r.result === 'committed').at(-1)
  const rows = new Set(receipt?.changes.map(c => c.row_id))
  // A receipt also contains repair checks for orders outside this task's scope.
  const checks = receipt?.checks.filter(c => c.category !== 'repair' || [...rows].some(id => c.check_id === `repair:${id}`))
  return !!checks?.length && checks.every(c => c.status === 'preserved' || c.status === 'repaired')
}

export function terminalLabel(status: RunStatus | undefined, repaired: boolean): string {
  return status === 'partially_succeeded' ? 'Partly repaired' : status === 'failed' ? 'Failed' : status === 'cancelled' ? 'Cancelled' : status === 'blocked' ? repaired ? 'Stopped after a repair' : 'Stopped before any repair' : repaired ? 'Repaired' : 'Finished without a recorded repair'
}
