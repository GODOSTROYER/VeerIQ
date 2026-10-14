import { Ban, Check, X } from 'lucide-react'
import type { PlanBinding, TaskGrant } from '@/api/types'
import { formatDateTime, pluralize } from '@/lib/format'
import { fieldLabel, tenantName, toolLabel, toolSummary, GRANT_STATUS } from '@/lib/labels'
import { Technical } from '@/lib/detail'
import { NumberRoll } from '@/components/motion'
import { Digest, Disclosure, EmptyState, ErrorState, Skeleton } from '@/components/ui'

export interface ScopeColumnProps {
  grant: TaskGrant | undefined
  plan: PlanBinding | undefined
  steps: number
  replans: number
  commits: number
  offPlanTools: string[]
  loading: boolean
  defaultOpen?: boolean
  error?: Error
}

export function ScopeColumn({ grant, plan, steps, replans, commits, offPlanTools, loading, defaultOpen = false, error }: ScopeColumnProps) {
  if (loading) return <div className="rounded-xl border border-line bg-raised p-4" role="status" aria-label="Loading task and scope"><Skeleton className="h-4 w-32" /><Skeleton className="mt-2 h-3 w-48 max-w-full" /></div>
  if (!grant) return <div className="rounded-xl border border-line bg-raised p-4">{error ? <ErrorState compact title="Task scope did not load" error={error} /> : <EmptyState compact title="Scope is not available yet" description="The authorized task appears here when the run loads." />}</div>
  const recordNoun = grant.workflow === 'rewindsafe.import_recovery' ? 'records' : 'orders'
  const orders = grant.resources.order ?? []
  const reviewOrders = grant.reviewable.order ?? []
  const planned = plan?.steps ?? []
  return <section className="rounded-xl border border-line bg-raised p-4" aria-label="Task and scope">
    <Disclosure className="border-0 bg-transparent [&>button]:px-0 [&>button]:py-1 [&>div>div]:px-0" defaultOpen={defaultOpen} summary={<span><span className="font-semibold text-ink">Task & scope</span><span className="mt-0.5 block text-xs font-normal text-ink-3">{orders.length + reviewOrders.length} {recordNoun} · {commits} of {grant.limits.max_commits} commits used</span></span>}>
      <p className="mb-3 text-[13px] leading-relaxed text-ink-2">{grant.purpose}</p>
      <ul className="space-y-2 text-[13px] leading-snug text-ink-2">
        <li>May repair <span className="font-medium text-ink">{orders.join(' and ') || `no ${recordNoun} directly`}</span>.</li>
        {reviewOrders.length > 0 && <li>May repair <span className="font-medium text-ink">{reviewOrders.join(' and ')}</span> after a different person approves the exact change.</li>}
        <li>May change {grant.fields.map(fieldLabel).map(s => s.toLowerCase()).join(', ') || 'no fields'}.</li>
        <li>May commit {grant.limits.max_commits === 1 ? 'once' : `${grant.limits.max_commits} times`}. <span className="text-ink-3"><NumberRoll value={commits} /> used.</span></li>
        <li>{plan ? `Signed plan allows ${pluralize(planned.length, 'action')}.` : 'Waiting for a signed plan.'}</li>
        <li>Values must come from the approved snapshot for {tenantName(grant.tenant_id)}.</li>
      </ul>
      <Disclosure summary="Allowed actions" className="mt-3 border-0 bg-transparent [&>button]:px-0 [&>div>div]:px-0">
        <ul className="space-y-2">{(plan ? planned : grant.allowed_tools).map(t => <li key={t} className="flex items-start gap-2 text-[13px]"><Check className="mt-0.5 size-3.5 shrink-0 text-allow" aria-hidden /><div><p className="text-ink">{toolLabel(t)}</p><p className="text-xs text-ink-3">{toolSummary(t)}</p><Technical><p className="break-all font-mono text-xs text-ink-3">{t}</p></Technical></div></li>)}</ul>
      </Disclosure>
      <Disclosure summary="Never allowed" className="mt-2 border-0 bg-transparent [&>button]:px-0 [&>div>div]:px-0">
        {grant.prohibited_effects.length ? <ul className="space-y-2">{grant.prohibited_effects.map(effect => <li key={effect} className="flex items-start gap-2 text-[13px] text-ink-2"><Ban className="mt-0.5 size-3.5 shrink-0 text-block" aria-hidden />{effect}</li>)}</ul> : <p className="text-xs text-ink-3">No extra prohibitions were recorded.</p>}
      </Disclosure>
    </Disclosure>
    {offPlanTools.length > 0 && <div className="mt-3 border-t border-line pt-3"><p className="mb-2 text-xs font-medium text-block">Tried outside the signed plan</p><ul className="space-y-2">{offPlanTools.map(t => <li key={t} className="flex items-start gap-2 text-[13px] text-ink-2"><X className="mt-0.5 size-3.5 shrink-0 text-block" aria-hidden /><div>{toolLabel(t)}<span className="block text-xs text-ink-3">The agent tried this without a signed action.</span><Technical><span className="break-all font-mono text-xs">{t}</span></Technical></div></li>)}</ul></div>}
    <Technical><div className="mt-3 space-y-2 border-t border-line pt-3 text-xs text-ink-2">
      <p>{GRANT_STATUS[grant.status]} · Expires {formatDateTime(grant.expires_at)}</p>
      <p>Steps <NumberRoll value={steps} /> of {grant.limits.max_steps} · Revisions <NumberRoll value={replans} /> of {grant.limits.max_replans}</p>
      <p className="break-all font-mono">{grant.grant_id}</p><Digest value={grant.grant_digest} label="grant digest" />
      <p>ArmorIQ binds tool names, VeerIQ binds arguments.</p>
      <Disclosure summary="Exact grant, sources and limits"><pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sunken p-3 font-mono text-[11px]">{JSON.stringify(grant, null, 2)}</pre></Disclosure>
    </div></Technical>
  </section>
}
