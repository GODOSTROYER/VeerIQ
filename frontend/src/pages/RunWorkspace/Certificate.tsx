import { useState, type ReactNode } from 'react'
import { Ban, Check, CircleAlert, Copy, Download, FlaskConical, ShieldCheck, TriangleAlert, X, type LucideIcon } from 'lucide-react'
import type { InvariantCheck, RunEvent } from '@/api/types'
import { Badge, Button, Digest, Disclosure, NumberRoll } from '@/components/ui'
import { Technical } from '@/lib/detail'
import { tint } from '@/lib/color'
import { formatMoney, formatDateTime } from '@/lib/format'
import { INVARIANT_STATUS, RUN_STATUS, TONE_COLOR, toolLabel, type Tone } from '@/lib/labels'
import { isSimulatedEnforcement, LAYERS } from '@/lib/layers'
import { plannerBadgeText } from './Header'
import { rec, str, times } from './model'
import { decisionChecks, isHeld, repairedOrders, stoppedGroups, unrepairedOrders, type RepairedOrder, type StoppedGroup } from './proof'
import type { CardCtx } from './TimelineCards'
function CountUp({ value, className }: { value: number; className?: string }) { return <NumberRoll value={value} className={className} /> }
/* ─── Finish: the recovery certificate ─── */

const FINISH_ICON: Partial<Record<string, LucideIcon>> = { blocked: Ban, failed: CircleAlert, cancelled: Ban, partially_succeeded: TriangleAlert }

function Stat({ label, value, tone = 'neutral' }: { label: string; value: number | undefined; tone?: Tone }) {
  return (
    <div className="min-w-0">
      <div className="text-2xl font-semibold leading-none tabular" style={{ color: TONE_COLOR[tone] }}>
        {value === undefined ? <span className="text-base font-medium text-ink-3">Not reported</span> : <CountUp value={value} />}
      </div>
      <div className="mt-1.5 text-xs leading-snug text-ink-3">{label}</div>
    </div>
  )
}

function CertSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="min-w-0">
      <h4 className="text-xs font-medium text-ink-3">{title}</h4>
      <div className="mt-2">{children}</div>
    </section>
  )
}

/** One protected check. A check that is not preserved always shows its status. */
function CheckLine({ check }: { check: InvariantCheck }) {
  const held = isHeld(check)
  return (
    <li className="flex items-start gap-2 text-[13px] leading-snug text-ink-2">
      {held ? <Check className="mt-0.5 size-3.5 shrink-0 text-allow" aria-hidden /> : <X className="mt-0.5 size-3.5 shrink-0 text-block" aria-hidden />}
      <span>
        {check.label}
        {!held && <span className="text-ink-3"> · {INVARIANT_STATUS[check.status].label}</span>}
      </span>
    </li>
  )
}

function certificateText(args: {
  scenario: string
  headline: string
  repaired: RepairedOrder[]
  checks: InvariantCheck[]
  stopped: StoppedGroup[]
  effects: number | undefined
  planHash: string | null | undefined
  receiptDigest: string | undefined
  mode: string
  planner: string
  finishedAt: string | undefined
}): string {
  const lines = [`VeerIQ recovery certificate: ${args.scenario}`, `Result: ${args.headline}`]
  lines.push(
    args.repaired.length
      ? `Repaired: ${args.repaired.map((o) => `${o.orderId}${o.restoredCents ? ` (${formatMoney(o.restoredCents)} restored)` : ''}`).join(', ')}`
      : 'Repaired: nothing in this run',
  )
  if (args.checks.length) lines.push(`Preserved checks: ${args.checks.map((c) => `${c.label} (${c.status})`).join('; ')}`)
  lines.push(
    args.stopped.length
      ? `Stopped: ${args.stopped
          .map((g) => `${toolLabel(g.tool)} by ${g.layers.map((l) => `${LAYERS[l.layer].short}${l.simulated ? ' (simulated)' : ''}`).join(' and ')}`)
          .join('; ')}`
      : 'Stopped: no blocked request recorded; this run does not demonstrate an attack being stopped',
  )
  lines.push(`Forbidden effects observed: ${args.effects ?? 'not reported'}`)
  lines.push(`Enforcement: ${args.mode}. Planner: ${args.planner}.`)
  if (args.planHash) lines.push(`Plan hash: ${args.planHash}`)
  if (args.receiptDigest) lines.push(`Receipt digest: ${args.receiptDigest}`)
  if (args.finishedAt) lines.push(`Finished: ${formatDateTime(args.finishedAt)}`)
  return lines.join('\n')
}

export function Certificate({ event, ctx }: { event: RunEvent; ctx: CardCtx }) {
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState(false)
  const d = rec(event.data)
  const status = (str(d.status) ?? ctx.run?.status ?? 'succeeded') as keyof typeof RUN_STATUS
  const meta = RUN_STATUS[status] ?? RUN_STATUS.succeeded
  const color = TONE_COLOR[meta.tone]
  const Icon = FINISH_ICON[status] ?? ShieldCheck
  const summary = str(d.outcome_summary) ?? ctx.run?.outcome_summary ?? event.detail
  const metrics = rec(d.metrics)
  const effects = typeof metrics.forbidden_effects_observed === 'number' ? metrics.forbidden_effects_observed : undefined
  const commits = typeof metrics.commits === 'number' ? metrics.commits : ctx.view.commits
  const error = status === 'failed' ? (str(d.error) ?? str(ctx.run?.metadata?.error)) : undefined
  const unrepaired = status === 'partially_succeeded' ? unrepairedOrders(ctx.grant, ctx.view) : []
  const headline =
    status === 'succeeded'
      ? ctx.view.receipts.length ? 'Recovery completed with a recorded receipt' : 'Run completed with recorded decisions'
      : status === 'partially_succeeded'
        ? 'Partly repaired'
        : status === 'blocked'
          ? 'Stopped before any change'
          : status === 'failed'
            ? 'The run failed'
            : status === 'cancelled'
              ? 'Run cancelled'
              : meta.label

  const repaired = repairedOrders(ctx.view)
  /* The same checks the "Must stay true" list shows, so the counts agree across the page. */
  const preserved = decisionChecks(ctx.checks)
  const notPreserved = preserved.filter((c) => !isHeld(c))
  const stopped = stoppedGroups(ctx.view)
  const simulated = isSimulatedEnforcement(ctx.enforcement)
  const receipt = ctx.view.receipts[ctx.view.receipts.length - 1]
  const planHash = ctx.plan?.plan_hash ?? ctx.run?.plan?.plan_hash
  const planner = ctx.run ? plannerBadgeText(ctx.run) : 'Unknown planner'
  const finishedAt = ctx.run?.finished_at ?? event.ts
  const restored = repaired.reduce((s, o) => s + (o.restoredCents ?? 0), 0)

  const copy = async () => {
    const text = certificateText({
      scenario: ctx.scenarioTitle ?? 'Recovery run',
      headline,
      repaired,
      checks: preserved,
      stopped,
      effects,
      planHash,
      receiptDigest: receipt?.receipt_digest,
      mode: simulated ? 'simulated ArmorIQ' : 'live ArmorIQ',
      planner,
      finishedAt,
    })
    try {
      await navigator.clipboard.writeText(text)
      setCopyError(false)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setCopyError(true)
    }
  }

  return (
    <article
      id="run-certificate"
      className="@container rounded-2xl border p-5"
      style={{ borderColor: tint(color, 50), background: 'var(--bg-raised)' }}
    >
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl" style={{ color, background: tint(color, 18) }}>
          <Icon className="size-[18px]" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-lg font-semibold leading-tight tracking-[-0.02em] text-ink">Recovery record</h3>
          <Disclosure className="border-0 bg-transparent [&>button]:px-0" summary="Recorded outcome"><p className="text-sm text-ink-2">{headline}. {summary || event.title}</p></Disclosure>
        </div>
        {simulated ? (
          <Badge tone="hold" dashed size="sm" icon={<FlaskConical />}>
            Simulated ArmorIQ
          </Badge>
        ) : (
          <Badge color="var(--layer-armoriq)" size="sm" icon={<ShieldCheck />}>
            Live ArmorIQ
          </Badge>
        )}
      </div>

      <div className="mt-4 grid gap-5 border-t border-line pt-4 @2xl:grid-cols-3">
        <CertSection title="Repaired">
          {repaired.length === 0 ? (
            <p className="text-[13px] text-ink-3">Nothing was repaired in this run.</p>
          ) : (
            <ul className="space-y-1.5">
              {repaired.map((o) => (
                <li key={o.orderId} className="flex items-baseline justify-between gap-3 text-[13px]">
                  <span className="font-mono text-ink">{o.orderId}</span>
                  <span className="tabular" style={{ color: 'var(--outcome-allow)' }}>
                    {o.restoredCents ? `${formatMoney(o.restoredCents)} restored` : 'repaired'}
                  </span>
                </li>
              ))}
              {repaired.length > 1 && restored > 0 && (
                <li className="flex items-baseline justify-between gap-3 border-t border-line pt-1.5 text-[13px] font-medium text-ink">
                  <span>Total</span>
                  <span className="tabular">{formatMoney(restored)}</span>
                </li>
              )}
            </ul>
          )}
        </CertSection>

        <CertSection title="Preserved">
          {preserved.length === 0 ? (
            <p className="text-[13px] text-ink-3">{ctx.checks ? 'No protected decisions on record.' : 'Detailed historical protected checks were not recorded for this run.'}</p>
          ) : (
            <div className="space-y-2.5">
              <p className="text-[13px] leading-snug text-ink-2">
                {notPreserved.length === 0
                  ? `All ${preserved.length} recorded checks preserved.`
                  : `${preserved.length - notPreserved.length} of ${preserved.length} recorded checks preserved.`}
              </p>
              {notPreserved.length > 0 && <ul className="space-y-1.5">{notPreserved.map((c) => <CheckLine key={c.check_id} check={c} />)}</ul>}
              <Disclosure className="border-0 bg-transparent [&>button]:px-0 [&>button]:py-1" summary={`Show all ${preserved.length} checks`}>
                <ul className="space-y-1.5">{preserved.map((c) => <CheckLine key={c.check_id} check={c} />)}</ul>
              </Disclosure>
            </div>
          )}
        </CertSection>

        <CertSection title="Stopped">
          {stopped.length === 0 ? (
            <p className="text-[13px] text-ink-3">Nothing needed stopping in this run.</p>
          ) : (
            <ul className="space-y-2">
              {stopped.map((g) => (
                <li key={g.tool} className="text-[13px] leading-snug text-ink-2">
                  <span className="font-medium text-ink">{toolLabel(g.tool)}</span>
                  <span className="text-ink-3">, attempted {times(g.attempts)}</span>
                  <span className="mt-1 flex flex-wrap gap-1">
                    {g.layers.map((l) => (
                      <Badge key={l.layer} size="sm" color={LAYERS[l.layer].color} dashed={l.simulated}>
                        {LAYERS[l.layer].short}
                        {l.simulated ? ' (simulated)' : ''}
                      </Badge>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CertSection>
      </div>

      <Technical><div className="mt-4 flex flex-wrap gap-6">
        <Stat label="Forbidden proposals blocked" value={ctx.view.blockedProposals} tone={ctx.view.blockedProposals > 0 ? 'good' : 'neutral'} />
        <Stat label="Forbidden effects observed" value={effects} tone={effects === undefined ? 'neutral' : effects === 0 ? 'good' : 'bad'} />
        <Stat label={commits === 1 ? 'Commit' : 'Commits'} value={commits} tone={commits > 0 ? 'good' : 'neutral'} />
      </div></Technical>

      {error && <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-lg border border-line bg-black/30 p-3 font-mono text-xs leading-relaxed text-ink-2">{error}</pre>}
      {unrepaired.length > 0 && (
        <div className="mt-4">
          <h4 className="text-[13px] font-semibold text-ink">What was not repaired, and why</h4>
          <ul className="mt-2 space-y-2">
            {unrepaired.map((u) => (
              <li key={u.orderId} className="flex gap-2.5 text-[13px] leading-snug text-ink-2">
                <span className="mt-0.5 font-mono" style={{ color }}>
                  {u.orderId}
                </span>
                <span>{u.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t pt-3" style={{ borderColor: tint(color, 22) }}>
        <Technical><div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-ink-3">
          {planHash && (
            <span className="inline-flex items-center gap-1.5">
              Plan <Digest value={planHash} label="plan hash" head={8} tail={4} />
            </span>
          )}
          {receipt && (
            <span className="inline-flex items-center gap-1.5">
              Receipt <Digest value={receipt.receipt_digest} label="receipt digest" head={8} tail={4} />
            </span>
          )}
          <span>{planner}</span>
          <span>{formatDateTime(finishedAt)}</span>
          <span className="break-all font-mono">Run {ctx.run?.run_id}</span>
        </div></Technical>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" icon={copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />} onClick={() => void copy()}>
            {copied ? 'Copied' : 'Copy summary'}
          </Button>
          <Button size="sm" variant="outline" icon={<Download className="size-3.5" />} loading={ctx.exporting} onClick={ctx.onExport}>
            Export evidence
          </Button>
        </div>
      </div>
      {copyError && <p role="alert" className="mt-2 text-xs text-ink-2">Clipboard unavailable. Export evidence to keep the complete record.</p>}
      <Technical><Disclosure summary="Complete finish event"><pre className="overflow-x-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(event, null, 2)}</pre></Disclosure></Technical>
    </article>
  )
}
