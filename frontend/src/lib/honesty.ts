import type { ApprovalRecord, ExecutionReceipt, Run, RunStatus } from '@/api/types'

/**
 * Honest end-of-run wording. Never claims "no writes" unless the data shows zero commits,
 * and never calls every non-success a rejection.
 */
export interface RunOutcomeLabel {
  kind: 'committed' | 'partial' | 'rejected' | 'blocked' | 'failed' | 'cancelled' | 'unknown'
  tone: 'good' | 'neutral' | 'harm'
  title: string
}

interface OutcomeInput {
  run: Pick<Run, 'status'>
  approvals?: Pick<ApprovalRecord, 'status'>[]
  receipts?: Pick<ExecutionReceipt, 'result'>[]
  /** RunMetrics.commits when the API returned it. */
  commits?: number | null
}

export function describeRunOutcome({ run, approvals, receipts, commits }: OutcomeInput): RunOutcomeLabel {
  const status: RunStatus = run.status
  // The commit count is only known when the API gave us a receipt list or a commit metric.
  const known = receipts !== undefined || (commits !== undefined && commits !== null)
  const committed = Math.max(commits ?? 0, (receipts ?? []).filter((r) => r.result === 'committed').length)
  const writes = !known
    ? ' Whether anything was written is not shown here.'
    : committed === 0
      ? ' No writes were made.'
      : ` ${committed} commit${committed === 1 ? '' : 's'} had already been made.`
  const rejectedByApprover = (approvals ?? []).some((a) => a.status === 'rejected')

  if (status === 'succeeded') return { kind: 'committed', tone: 'good', title: 'Approved and committed, in one locked transaction.' }
  if (status === 'partially_succeeded') return { kind: 'partial', tone: 'neutral', title: `Partly applied.${writes}` }
  if (status === 'cancelled') return { kind: 'cancelled', tone: 'neutral', title: `Cancelled before completion.${writes}` }
  if (status === 'failed') return { kind: 'failed', tone: 'harm', title: `Failed.${writes}` }
  if (status === 'blocked') {
    return rejectedByApprover
      ? { kind: 'rejected', tone: 'neutral', title: `Rejected by the approver.${writes}` }
      : { kind: 'blocked', tone: 'neutral', title: `Blocked by a gate.${writes}` }
  }
  return { kind: 'unknown', tone: 'neutral', title: `Ended with status "${String(status).replace(/_/g, ' ')}".${writes}` }
}

/** What actually plans the steps, for the live feed. */
export function livePlannerNote(
  planner: { kind?: string | null; name?: string | null; provider?: string | null } | null | undefined,
): string {
  if (!planner || !planner.kind) return 'Working… this can take about a minute.'
  if (planner.kind === 'llm') {
    const who = [planner.provider, planner.name].filter(Boolean).join(' ')
    return `Working… Live model${who ? `: ${who}` : ''} is choosing each step, so this can take about a minute.`
  }
  if (planner.kind === 'harness') return 'Working… a boundary test harness is proposing steps.'
  return 'Working… Scripted planner (no model is deciding); the gates still check every step.'
}

/** Badge for the run card, from the planner kind that is actually in use. */
export function plannerBadge(kind: string | null | undefined): string {
  if (kind === 'llm') return 'live model'
  if (kind === 'harness') return 'boundary harness'
  return 'scripted planner'
}
