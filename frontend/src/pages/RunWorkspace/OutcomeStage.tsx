import { Ban, ShieldCheck } from 'lucide-react'
import { Button, Digest } from '@/components/ui'
import { Technical } from '@/lib/detail'
import { LAYERS } from '@/lib/layers'
import { actionSentence, joinList, rec, str } from './model'
import { isHeld, repairedOrders } from './proof'
import { terminalLabel } from './stageModel'
import type { CardCtx } from './TimelineCards'

export function OutcomeStage({ ctx, replay, heading = false, compact = false }: { ctx: CardCtx; replay: boolean; heading?: boolean; compact?: boolean }) {
  const repaired = repairedOrders(ctx.view)
  const status = ctx.view.status ?? ctx.run?.status
  const stopped = ctx.view.proposals.find(p => p.blocker?.decisive) ?? ctx.view.proposals.find(p => p.blocker)
  const protectedChecks = ctx.checks?.filter(c => c.category !== 'repair') ?? []
  const held = protectedChecks.filter(isHeld)
  const good = status === 'succeeded' && repaired.length > 0
  const color = good ? 'var(--outcome-allow)' : status === 'cancelled' ? 'var(--text-2)' : status === 'partially_succeeded' ? 'var(--outcome-hold)' : 'var(--outcome-block)'
  const Icon = good ? ShieldCheck : Ban
  if (heading) return <div className="flex flex-wrap items-start justify-between gap-2">
    <div><div className="flex items-center gap-3"><Icon className="size-6 shrink-0" style={{ color }} aria-hidden /><h2 className="text-xl font-semibold tracking-tight sm:text-2xl">{terminalLabel(status, repaired.length > 0)}</h2></div>
    {replay && <p className="mt-1 text-xs text-ink-2">Recorded replay</p>}</div>
    {stopped && <Button size="sm" variant="secondary" onClick={() => ctx.onSelect(stopped.proposalId)}>Show the blocked request</Button>}
  </div>
  if (compact) {
    const commits = ctx.view.receipts.filter(r => r.result === 'committed').length
    const request = stopped?.tool === 'restore_access_grant'
      ? `restore access to ${str(stopped.args.grant_id) ?? 'the access grant'}`
      : stopped ? actionSentence(stopped.tool, stopped.args, ctx.action) : undefined
    const stoppedSummary = stopped?.blocker
      ? `${request} · ${LAYERS[stopped.blocker.layer].short}${stopped.blocker.simulated ? ' (simulated)' : ''}`
      : ctx.view.proposals.some(p => p.unavailable) ? 'Enforcement unavailable · failed closed'
      : ctx.view.rejections.length ? 'Repair refused before writing' : 'No blocked request recorded'
    return <div aria-label="Run outcome">
      <dl className="space-y-4 text-[13px] leading-5">
        {[
          ['Stopped', stoppedSummary],
          ['Repaired', repaired.length ? `${joinList(repaired.map(o => o.orderId))} · ${commits} ${commits === 1 ? 'commit' : 'commits'}` : 'Nothing · no repair committed'],
          ['Protected', protectedChecks.length ? `${held.length} of ${protectedChecks.length} decisions kept` : 'Verification not recorded'],
        ].map(([label, summary]) => <div key={label} data-outcome-result className="flex gap-1"><dt className="shrink-0 font-medium text-ink">{label}:</dt><dd className="text-ink-2">{summary}</dd></div>)}
      </dl>
      <a href="#run-certificate" className="mt-5 inline-flex min-h-11 items-center rounded-lg text-[13px] font-medium text-ink-2 underline decoration-line-strong underline-offset-4 transition-colors hover:text-ink active:text-ink">Details · Recovery record</a>
    </div>
  }
  return <div aria-label="Run outcome">
    <dl className="space-y-3 text-[13px] leading-relaxed sm:grid sm:grid-cols-3 sm:gap-6 sm:space-y-0 sm:text-sm">
      <div><dt className="font-medium text-ink">Stopped</dt><dd className="text-ink-2">{stopped?.blocker ? `${actionSentence(stopped.tool, stopped.args, ctx.action)} · ${LAYERS[stopped.blocker.layer].label}${stopped.blocker.simulated ? ' (simulated)' : ''}. Nothing changed from this request.` : ctx.view.proposals.some(p => p.unavailable) ? 'Enforcement was unavailable; the request failed closed.' : ctx.view.rejections.length ? 'The repair was refused before writing.' : 'No blocked request was recorded.'}</dd></div>
      <div><dt className="font-medium text-ink">Repaired</dt><dd className="text-ink-2">{repaired.length ? `${joinList(repaired.map(o => o.orderId))} restored from the approved snapshot; ${ctx.view.receipts.filter(r => r.result === 'committed').length} recorded commit.` : 'Nothing. No repair committed in this run.'}</dd></div>
      <div><dt className="font-medium text-ink">Protected</dt><dd className="text-ink-2">{held.length ? `${joinList(held.map(c => c.label), 5)}.${held.length < protectedChecks.length ? ' Some checks remain unconfirmed.' : ''}` : 'Detailed historical checks were not recorded for this run. Current state cannot certify the past.'}</dd></div>
    </dl>
    <Technical><div className="mt-4 space-y-2 border-t border-line pt-3 text-xs text-ink-2"><p>{str(rec(ctx.view.finish?.data).outcome_summary) ?? ctx.run?.outcome_summary}</p><p>ArmorIQ binds tool names, VeerIQ binds arguments.</p>{ctx.plan?.plan_hash && <Digest value={ctx.plan.plan_hash} label="plan hash" />}</div></Technical>
  </div>
}
