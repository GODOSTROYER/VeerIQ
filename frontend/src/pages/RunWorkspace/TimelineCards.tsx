import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, useReducedMotion } from 'motion/react'
import {
  ArrowDown,
  ArrowRight,
  Ban,
  Check,
  ChevronDown,
  FileDiff,
  FileWarning,
  ShieldCheck,
  Siren,
  TriangleAlert,
  UserCheck,
} from 'lucide-react'
import type { ApprovalRecord, Decision, ExecutionManifest, ExecutionReceipt, InvariantCheck, PlanBinding, Run, RunEvent, TaskGrant } from '@/api/types'
import { cn } from '@/lib/cn'
import { tint } from '@/lib/color'
import { formatClock, formatCountdown, formatDateTime, hasTime, pluralize } from '@/lib/format'
import { APPROVAL_STATUS, fieldLabel, invariantLabel, TONE_COLOR, toolLabel, type Tone } from '@/lib/labels'
import { isSimulatedEnforcement, LAYERS, OUTCOMES, sourceLabel, type EnforcementFacts } from '@/lib/layers'
import { humanReason, LOCAL_CHECK_EXPLAINER, NOTE_FOOTER, sourceWhere, splitInjection } from '@/lib/reasons'
import { Badge, AnimatedNumber, Button, Digest, Tooltip } from '@/components/ui'
import { Technical } from '@/lib/detail'
import { Disclosure } from '@/components/ui'
import { DecisionCard } from '@/components/domain'
import { useNow } from './hooks'
import {
  argOrderIds,
  formatFieldValue,
  isEmptyValue,
  keyArgs,
  rec,
  scrubPlaceholders,
  str,
  type ActionCtx,
  type Annotation,
  type ProposalItem,
  type RunView,
} from './model'
import { externalSentence } from './proof'
import type { RecordedProtectedEvidence } from './proof'

export interface CardCtx {
  action: ActionCtx
  plan: PlanBinding | undefined
  run: Run | undefined
  grant: TaskGrant | undefined
  view: RunView
  /** Prohibited handler entries recorded for this run (from run metrics). */
  handlerEntries: number | undefined
  nameOf: (identityId: string | null | undefined) => string
  /** Shared facts behind every "Live" or "Simulated" label on the page. */
  enforcement: EnforcementFacts
  selectedId: string | undefined
  onSelect: (proposalId: string) => void
  /** True while the run is live and not being replayed: countdowns may tick. */
  ticking: boolean
  /** Protected-state checks (for the certificate). */
  checks: InvariantCheck[] | undefined
  checkEvidence: RecordedProtectedEvidence | undefined
  scenarioTitle: string | undefined
  onExport: () => void
  exporting: boolean
  /** Present when the viewer is the run's operator and a same-tenant reviewer exists. */
  reviewAs: { name: string; go: (approvalId: string) => Promise<void> } | undefined
}


/** Counts up from zero on first render. */
function CountUp({ value, className }: { value: number; className?: string }) {
  const [v, setV] = useState(0)
  useEffect(() => {
    setV(value)
  }, [value])
  return <AnimatedNumber value={v} className={className} />
}

/* ─── Decision chips ─── */

export function DecisionChips({ decisions, tool }: { decisions: Decision[]; tool?: string }) {
  if (decisions.length === 0) return null
  return (
    <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Decision at each layer">
      {decisions.map((d) => {
        const layer = LAYERS[d.layer]
        const outcome = OUTCOMES[d.outcome]
        const Icon = layer.icon
        const verdict = d.shadow ? (d.outcome === 'allow' ? 'would allow' : 'would block') : outcome.label.toLowerCase()
        const name = d.simulated ? `${layer.short} (simulated)` : layer.short
        return (
          <li key={d.decision_id}>
            <Tooltip
              content={
                <span className="block max-w-[280px] whitespace-normal">
                  <span className="block font-medium">{sourceLabel(d)}</span>
                  <span className="mt-0.5 block text-ink-2">{humanReason(d, tool)}</span>
                  {d.source === 'armoriq.sdk.plan_binding' ? (
                    <span className="mt-0.5 block text-ink-3">Checked locally, no network call</span>
                  ) : (
                    d.latency_ms != null && <span className="mt-0.5 block text-ink-3">{Math.round(d.latency_ms)} ms</span>
                  )}
                </span>
              }
            >
              <span className="inline-flex">
                <Badge color={outcome.color} dashed={d.shadow || d.simulated} size="sm" icon={<Icon style={{ color: layer.color }} />}>
                  {name}: {verdict}
                </Badge>
              </span>
            </Tooltip>
          </li>
        )
      })}
    </ul>
  )
}

/* ─── Proposal ─── */

function ArgList({ item, ctx }: { item: ProposalItem; ctx: CardCtx }) {
  const args = keyArgs(item.args, ctx.action)
  if (args.length === 0) return null
  return (
    <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
      {args.map((a) => (
        <div key={a.label} className="flex min-w-0 items-baseline gap-1.5 text-xs">
          <dt className="text-ink-3">{a.label}</dt>
          <dd className={cn('min-w-0 break-words text-ink-2', a.mono && 'font-mono text-[12px]')}>{a.value}</dd>
        </div>
      ))}
    </dl>
  )
}

function sourceNote(source: ProposalItem['source']): string | null {
  if (source === 'boundary_harness') return 'Boundary test probe'
  if (source === 'mcp') return 'From an MCP client'
  if (source === 'operator') return 'Operator request'
  return null
}

export function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' })
}

/** Which untrusted note most plausibly carried this instruction. */
export function sourceNoteFor(item: ProposalItem, ctx: CardCtx): Annotation | undefined {
  const notes = ctx.view.annotations
  if (notes.length === 0) return undefined
  const touchesBeacon = item.args.tenant_id === 'beacon' || argOrderIds(item.args).some((id) => id.startsWith('B-'))
  if (item.tool !== 'restore_access_grant' && !touchesBeacon) return undefined
  const grantId = str(item.args.grant_id)
  return notes.find((n) => n.body.includes(item.tool) || (grantId ? n.body.includes(grantId) : false)) ?? notes[0]
}

export function ProposalCard({ item, ctx }: { item: ProposalItem; ctx: CardCtx }) {
  const note = sourceNoteFor(item, ctx)
  return <div className="space-y-3 text-[13px] leading-relaxed text-ink-2">
    <ArgList item={item} ctx={ctx} />
    {item.rationale && <p>The agent said: {scrubPlaceholders(item.rationale)}</p>}
    {item.resultSummary && <p>{item.resultSummary}</p>}
    {note && <p>Instruction matches <button className="rounded underline underline-offset-4 hover:text-ink" onClick={() => scrollToId(`note-${note.annotationId}`)}>the untrusted note</button>.</p>}
    {item.blocker && <>
      <p>{humanReason(item.blocker, item.tool)}</p>
      <p>{LAYERS[item.blocker.layer].description}</p>
      {item.blocker.layer !== 'armoriq' && item.decisions.some(d => d.layer === 'armoriq' && !d.shadow && d.outcome === 'allow') && <p>ArmorIQ allowed the tool name. VeerIQ checked the arguments and stopped the request.</p>}
      <p>Restricted handler entered: {ctx.handlerEntries === undefined ? 'not reported' : `${ctx.handlerEntries} counted by the database`}.</p>
      {ctx.plan && <div><p className="font-medium text-ink">Actions in the signed plan</p><ul className="mt-2 flex flex-wrap gap-1.5">{ctx.plan.steps.map(t => <li key={t}><Badge size="sm">{toolLabel(t)}</Badge></li>)}</ul><p className="mt-2">{toolLabel(item.tool)}: {ctx.plan.steps.includes(item.tool) ? 'in the plan; a later gate refused it' : 'outside the signed plan'}.</p></div>}
    </>}
    <DecisionChips decisions={item.decisions} tool={item.tool} />
    <Technical><div className="space-y-3">
      <p>{toolLabel(item.tool)}{item.stepIndex === undefined ? '' : `, step ${item.stepIndex + 1}`} · {sourceNote(item.source) ?? 'Agent request'}</p>
      {ctx.plan?.plan_hash && <div className="flex flex-wrap items-center gap-2">Signed plan <Digest value={ctx.plan.plan_hash} label="plan hash" /></div>}
      {item.decisions.map(d => <div key={d.decision_id}><p>{sourceWhere(d.source, d.latency_ms)}</p>{d.source === 'armoriq.sdk.plan_binding' && <p>{LOCAL_CHECK_EXPLAINER}</p>}<DecisionCard decision={d} /></div>)}
      <Disclosure summary="Complete request and decisions"><pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[11px]">{JSON.stringify(item, null, 2)}</pre></Disclosure>
    </div></Technical>
  </div>
}

export function BlockedCard(props: { item: ProposalItem; ctx: CardCtx }) { return <ProposalCard {...props} /> }

/* ─── Untrusted note ─── */

export function UntrustedNoteCard({ annotation: a, ctx }: { annotation: Annotation; ctx: CardCtx }) {
  const color = 'var(--outcome-hold)'
  const spans = splitInjection(a.body)
  const led = ctx.view.proposals.find((p) => p.blocker && sourceNoteFor(p, ctx)?.annotationId === a.annotationId)
  return (
    <article
      id={`note-${a.annotationId}`}
      className="rounded-2xl border border-dashed p-4"
      style={{ borderColor: tint(color, 60), background: `linear-gradient(135deg, ${tint(color, 10)}, transparent 75%)` }}
    >
      <div className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg" style={{ color, background: tint(color, 18) }}>
          <FileWarning className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold leading-snug text-ink">Untrusted note attached to the snapshot</h3>
          <p className="mt-0.5 text-xs text-ink-3">
            {a.annotationId}, written by {a.author}
            {a.createdAt ? `, ${formatDateTime(a.createdAt)}` : ''}
          </p>
        </div>
        <Badge size="sm" tone="hold" dashed>
          Untrusted
        </Badge>
      </div>
      <blockquote className="mt-3 pl-0 text-[13px] leading-relaxed text-ink-2" style={{ borderColor: tint(color, 55) }}>
        {spans.map((s, i) =>
          s.mark ? (
            <mark key={i} className="rounded px-0.5 text-ink" style={{ background: tint('var(--outcome-block)', 22) }}>
              {s.text}
            </mark>
          ) : (
            <span key={i}>{s.text}</span>
          ),
        )}
      </blockquote>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="text-xs leading-snug text-ink-3">{NOTE_FOOTER}</p>
        {led && (
          <button
            type="button"
            onClick={() => scrollToId(`proposal-${led.proposalId}`)}
            className="inline-flex items-center gap-1 rounded-md text-xs font-medium text-ink-2 underline decoration-dotted underline-offset-4 hover:text-ink"
          >
            What the agent did next
            <ArrowDown className="size-3" aria-hidden />
          </button>
        )}
      </div>
    </article>
  )
}

/* ─── Approval ─── */

const SPONSOR_LABEL: Record<NonNullable<ApprovalRecord['sponsor_status']>, string> = {
  pending: 'ArmorIQ delegation pending',
  approved: 'ArmorIQ delegation approved',
  rejected: 'ArmorIQ delegation rejected',
  timeout: 'ArmorIQ delegation timed out',
  simulated: 'Simulated ArmorIQ delegation',
}

function ReviewAsButton({ approvalId, reviewAs }: { approvalId: string; reviewAs: NonNullable<CardCtx['reviewAs']> }) {
  const [busy, setBusy] = useState(false)
  return (
    <Button
      size="sm"
      variant="primary"
      loading={busy}
      icon={<UserCheck className="size-3.5" />}
      onClick={() => {
        setBusy(true)
        void reviewAs.go(approvalId).finally(() => setBusy(false))
      }}
    >
      Review as {reviewAs.name}
    </Button>
  )
}

export function ApprovalCard({ approval: a, ctx }: { approval: ApprovalRecord; ctx: CardCtx }) {
  const pending = a.status === 'pending'
  const counting = pending && ctx.ticking
  const now = useNow(counting ? 1000 : 0)
  const total = Math.max(1, Date.parse(a.expires_at) - Date.parse(a.requested_at))
  const remaining = Date.parse(a.expires_at) - now
  const meta = APPROVAL_STATUS[a.status]
  const color = TONE_COLOR[pending ? 'hold' : meta.tone]
  const decider = ctx.nameOf(a.decided_by)
  const title = pending
    ? 'Waiting for a second reviewer'
    : a.status === 'approved'
      ? `Approved by ${decider}`
      : a.status === 'rejected'
        ? `Rejected by ${decider}`
        : a.status === 'cancelled'
          ? 'Review cancelled'
          : 'Review timed out'
  return (
    <article
      className="rounded-2xl border p-4"
      style={{ borderColor: tint(color, 45), background: `linear-gradient(135deg, ${tint(color, 10)}, transparent 70%)` }}
    >
      <div className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg" style={{ color, background: tint(color, 16) }}>
          <UserCheck className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold leading-snug text-ink">{title}</h3>
          <p className="mt-0.5 text-[13px] leading-snug text-ink-2">{a.reason}</p>
        </div>
        {counting ? (
          <div className="shrink-0 text-right" role="timer" aria-label="Time left for the reviewer to decide">
            <div className="tabular text-xl font-semibold leading-none" style={{ color: remaining > 0 ? color : 'var(--outcome-block)' }}>
              {remaining > 0 ? formatCountdown(remaining) : 'Expired'}
            </div>
            <div className="mt-1 text-xs text-ink-3">left to decide</div>
          </div>
        ) : (
          <Badge tone={pending ? 'hold' : meta.tone}>{pending ? 'Waiting' : meta.label}</Badge>
        )}
      </div>
      {counting && (
        <div className="mt-3 h-1 overflow-hidden rounded-full bg-surface-3" aria-hidden>
          <div className="h-full rounded-full origin-left transition-transform duration-150" style={{ transform: `scaleX(${Math.max(0, Math.min(1, remaining / total))})`, background: color }} />
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 pl-11 text-xs text-ink-3">
        <span className="inline-flex flex-wrap items-center gap-1.5">
          Covers
          {a.targets.map((t) => (
            <Badge key={t} size="sm" mono tone="neutral">
              {t}
            </Badge>
          ))}
        </span>
        <Technical inline><span className="inline-flex items-center gap-1.5">
          Exact payload <Digest value={a.payload_digest} label="payload digest" head={6} tail={4} />
        </span></Technical>
        {a.sponsor_status && (
          <Badge size="sm" tone="neutral" dashed={a.sponsor_status === 'simulated'} color={a.sponsor_status === 'simulated' ? 'var(--outcome-hold)' : 'var(--layer-armoriq)'}>
            {SPONSOR_LABEL[a.sponsor_status]}
          </Badge>
        )}
      </div>
      {pending ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 pl-11">
          {ctx.reviewAs && <ReviewAsButton approvalId={a.approval_id} reviewAs={ctx.reviewAs} />}
          <Link
            to="/approvals"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line-strong bg-surface-3 px-3 text-[13px] font-medium text-ink transition-colors hover:bg-white/[0.12]"
          >
            Open in Approvals
            <ArrowRight className="size-3.5" aria-hidden />
          </Link>
          <p className="basis-full text-xs text-ink-3">Only a different person from the one who started this run can decide. Expires {formatDateTime(a.expires_at)}.</p>
        </div>
      ) : (
        hasTime(a.decided_at) && (
          <p className="mt-2 pl-11 text-xs text-ink-3">
            Decided at {formatClock(a.decided_at)} UTC{a.note ? `. Note: ${a.note}` : ''}
          </p>
        )
      )}
    </article>
  )
}

/* ─── Manifest ─── */

const MANIFEST_STATUS: Record<ExecutionManifest['status'], { label: string; tone: Tone }> = {
  prepared: { label: 'Ready to apply', tone: 'info' },
  committed: { label: 'Applied', tone: 'good' },
  stale: { label: 'Out of date', tone: 'hold' },
  rejected: { label: 'Rejected', tone: 'bad' },
  superseded: { label: 'Superseded', tone: 'neutral' },
}

export function ManifestCard({ manifest, status }: { manifest: ExecutionManifest; status: ExecutionManifest['status'] }) {
  const [all, setAll] = useState(false)
  const orders = Array.from(new Set(manifest.changes.map((c) => c.row_id)))
  const shown = all ? manifest.changes : manifest.changes.slice(0, 6)
  const grouped = orders
    .map((id) => ({ id, changes: shown.filter((c) => c.row_id === id) }))
    .filter((g) => g.changes.length > 0)
  const meta = MANIFEST_STATUS[status]
  return (
    <article className="glass rounded-2xl p-4">
      <div className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-ink-2">
          <FileDiff className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold leading-snug text-ink">Repair prepared</h3>
          <p className="mt-0.5 text-xs text-ink-3">
            {pluralize(orders.length, 'order')}, {pluralize(manifest.changes.length, 'change')}, values taken from snapshot {manifest.snapshot_id}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
          {manifest.requires_review && <Badge tone="hold" icon={<UserCheck />}>Needs a second reviewer</Badge>}
          <Badge tone={meta.tone}>{meta.label}</Badge>
        </div>
      </div>
      <div className="mt-3 space-y-2 pl-11">
        {grouped.map((g) => (
          <div key={g.id} className="rounded-xl border border-line bg-black/20 px-3 py-2">
            <div className="font-mono text-[13px] font-medium text-ink">{g.id}</div>
            <ul className="mt-1 space-y-1">
              {g.changes.map((c) => (
                <li key={`${c.row_id}-${c.field}`} className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
                  <span className="w-28 shrink-0 text-ink-3">{fieldLabel(c.field)}</span>
                  <span className={cn('tabular', isEmptyValue(c.current_value) ? 'text-ink-3' : 'text-[var(--diff-bad)]')}>{formatFieldValue(c.field, c.current_value)}</span>
                  <ArrowRight className="size-3 self-center text-ink-3" aria-hidden />
                  <span className={cn('tabular font-medium', isEmptyValue(c.new_value) ? 'text-ink-3' : 'text-[var(--diff-good)]')}>{formatFieldValue(c.field, c.new_value)}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
        {manifest.changes.length > 6 && (
          <button
            type="button"
            onClick={() => setAll((v) => !v)}
            className="inline-flex items-center gap-1 text-xs font-medium text-ink-2 hover:text-ink"
          >
            <ChevronDown className={cn('size-3.5 transition-transform', all && 'rotate-180')} aria-hidden />
            {all ? 'Show fewer changes' : `Show all ${manifest.changes.length} changes`}
          </button>
        )}
        <Technical><div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
          Fingerprint of this exact repair <Digest value={manifest.content_digest} label="manifest digest" head={8} tail={4} />
        </div></Technical>
        {manifest.review_reason && <p className="text-xs text-ink-3">{manifest.review_reason}</p>}
      </div>
    </article>
  )
}

/* ─── Commit ─── */

function DrawnCheck() {
  return (
    <motion.svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <motion.path d="M5 12.5l4.5 4.5L19 7"  />
    </motion.svg>
  )
}

export function CommitCard({ receipt }: { receipt: ExecutionReceipt }) {
  const orders = Array.from(new Set(receipt.changes.map((c) => c.row_id)))
  const rows = receipt.effect_counts.rows_updated ?? orders.length
  const entries = receipt.effect_counts.prohibited_handler_entries
  const color = 'var(--outcome-allow)'
  return (
    <article className="rounded-2xl border p-4" style={{ borderColor: tint(color, 45), background: `linear-gradient(135deg, ${tint(color, 11)}, transparent 70%)` }}>
      <div className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-full" style={{ color, background: tint(color, 18) }}>
          <DrawnCheck />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold leading-snug text-ink">Repair committed</h3>
          <p className="mt-0.5 text-[13px] leading-snug text-ink-2">
            Written in one database transaction{hasTime(receipt.committed_at) ? ` at ${formatClock(receipt.committed_at)} UTC` : ''}. Orders touched: {orders.join(', ')}.
          </p>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-2xl font-semibold leading-none" style={{ color }}>
            <CountUp value={rows} />
          </div>
          <div className="mt-1 text-xs text-ink-3">{rows === 1 ? 'row updated' : 'rows updated'}</div>
        </div>
      </div>
      <Technical><div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 pl-11 text-xs text-ink-3">
        <span className="inline-flex items-center gap-1.5">
          Receipt <Digest value={receipt.receipt_digest} label="receipt digest" head={8} tail={4} />
        </span>
        <span className="inline-flex items-center gap-1.5">
          Operation <span className="font-mono text-[12px] text-ink-2">{receipt.operation_id}</span>
        </span>
        {entries !== undefined && (
          <span>
            Prohibited handler entries <span className="font-semibold text-ink">{entries}</span>
          </span>
        )}
      </div></Technical>
    </article>
  )
}

/* ─── Small items ─── */

export function RejectedCard({ event }: { event: RunEvent }) {
  const d = rec(event.data)
  const invariant = str(d.invariant)
  const color = 'var(--outcome-hold)'
  return (
    <article className="rounded-2xl border p-4" style={{ borderColor: tint(color, 45), background: `linear-gradient(135deg, ${tint(color, 10)}, transparent 70%)` }}>
      <div className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg" style={{ color, background: tint(color, 16) }}>
          <TriangleAlert className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold leading-snug text-ink">Repair not applied</h3>
          <p className="mt-0.5 text-[13px] leading-relaxed text-ink-2">{event.detail || str(d.reason) || event.title}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge tone="good">No data changed</Badge>
            {invariant && <Badge tone="hold">{invariantLabel(invariant)}</Badge>}
          </div>
        </div>
      </div>
    </article>
  )
}

export function DuplicateCard({ event }: { event: RunEvent }) {
  return (
    <article className="glass rounded-2xl border-dashed p-3.5">
      <p className="text-[13px] font-medium text-ink">{event.title}</p>
      {event.detail && <p className="mt-0.5 text-xs leading-snug text-ink-3">{event.detail}</p>}
      <div className="mt-2">
        <Badge tone="neutral" dashed>
          Same request, original receipt returned, nothing changed again
        </Badge>
      </div>
    </article>
  )
}

export function ReplanDivider({ event }: { event: RunEvent }) {
  const d = rec(event.data)
  const attempt = typeof d.attempt === 'number' ? d.attempt : undefined
  const reason = event.detail || str(d.reason)
  return (
    <div className="py-1">
      <div className="flex items-center gap-3">
        <span className="h-px flex-1 border-t border-dashed border-line-strong" aria-hidden />
        <span className="inline-flex items-center gap-2 text-[13px] font-medium text-ink-2">
          Agent revised its plan
          {attempt !== undefined && (
            <Badge size="sm" tone="neutral" dashed>
              Revision {attempt}
            </Badge>
          )}
        </span>
        <span className="h-px flex-1 border-t border-dashed border-line-strong" aria-hidden />
      </div>
      {reason && reason.includes(' ') && <p className="mt-1.5 text-center text-xs leading-snug text-ink-3">{reason}</p>}
    </div>
  )
}

export function ExternalCard({ event }: { event: RunEvent }) {
  const d = rec(event.data)
  const reason = str(d.reason)
  const color = 'var(--outcome-hold)'
  return (
    <article
      className="relative overflow-hidden rounded-2xl border p-4 pl-5"
      style={{ borderColor: tint(color, 55), background: `linear-gradient(100deg, ${tint(color, 14)}, transparent 75%)` }}
    >

      <div className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg" style={{ color, background: tint(color, 18) }}>
          <Siren className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold leading-snug" style={{ color }}>
            Meanwhile: {externalSentence(d, event.title)}
          </h3>
          {reason && <p className="mt-0.5 text-[13px] leading-snug text-ink-2">Reason on record: {reason}</p>}
          <p className="mt-1.5 text-xs leading-snug text-ink-3">
            {event.detail || 'Demo scenario event. It stands in for another team changing authority while the agent works.'}
          </p>
        </div>
      </div>
    </article>
  )
}

export function PlanCard({
  plan,
  event,
  latencyMs,
  matchedPolicies,
  simulated: sim,
}: {
  plan: PlanBinding | undefined
  event: RunEvent
  latencyMs?: number
  matchedPolicies?: string[]
  simulated: boolean
}) {
  return (
    <article className="glass rounded-2xl p-4">
      <div className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg" style={{ color: 'var(--layer-armoriq)', background: tint('var(--layer-armoriq)', 16) }}>
          <ShieldCheck className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold leading-snug text-ink">{sim ? 'Plan bound (simulated ArmorIQ)' : 'ArmorIQ signed the plan'}</h3>
          <p className="mt-0.5 text-[13px] leading-snug text-ink-2">
            {sim
              ? 'The simulation fixed the list of allowed actions before the agent started. This is not a signature from the live ArmorIQ service.'
              : 'The list of allowed actions was signed before the agent started. Anything outside it is stopped.'}

          </p>
          {plan && plan.steps.length > 0 && (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {plan.steps.map((s) => (
                <li key={s}>
                  <Badge size="sm" tone="neutral">
                    {toolLabel(s)}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
          <Technical><div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-ink-3">
            {plan?.plan_hash && (
              <span className="inline-flex flex-wrap items-center gap-1.5">
                Plan fingerprint <Digest value={plan.plan_hash} label="plan hash" />
              </span>
            )}
            {latencyMs != null && <span>Signing: {latencyMs} ms</span>}{matchedPolicies && matchedPolicies.length > 0 && <span>Matched policy: {matchedPolicies.join(', ')}</span>}
          </div></Technical>
        </div>
      </div>
      <span className="sr-only">{event.title}</span>
    </article>
  )
}

/** Shown while ArmorIQ signs the plan, which takes about 5 s with the live service. */
export function PlanSigningCard({ ctx, requestedAt }: { ctx: CardCtx; requestedAt: string | undefined }) {
  const reduce = useReducedMotion()
  const simulated = isSimulatedEnforcement(ctx.enforcement)
  const started = Date.parse(requestedAt ?? ctx.run?.created_at ?? '')
  const now = useNow(ctx.ticking ? 100 : 0)
  const elapsed = ctx.ticking && Number.isFinite(started) ? Math.max(0, now - started) : undefined
  const tools = ctx.grant?.allowed_tools ?? []
  const color = 'var(--layer-armoriq)'
  return (
    <article
      role="status"
      aria-live="polite"
      className="relative overflow-hidden rounded-2xl border p-4"
      style={{ borderColor: tint(color, 45), background: `linear-gradient(135deg, ${tint(color, 12)}, ${tint(color, 3)} 70%)` }}
    >
      <div className="flex items-start gap-3">
        <span className="relative grid size-8 shrink-0 place-items-center rounded-lg" style={{ color, background: tint(color, 18) }}>
          <ShieldCheck className="size-4" aria-hidden />
          {!reduce && <span className="pulse-dot absolute -right-0.5 -top-0.5 size-2 rounded-full" style={{ background: color }} aria-hidden />}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold leading-snug text-ink">{simulated ? 'Binding the plan (simulated)' : 'ArmorIQ is signing the recovery plan'}</h3>
          <p className="mt-0.5 text-[13px] leading-snug text-ink-2">
            {simulated
              ? 'The local simulation is fixing the list of allowed actions. No call goes to ArmorIQ in this mode.'
              : 'The agent starts as soon as the plan is signed. Anything outside the plan will be refused.'}
          </p>
        </div>
        {elapsed !== undefined && (
          <div className="shrink-0 text-right">
            <div className="tabular text-xl font-semibold leading-none" style={{ color }}>
              {(elapsed / 1000).toFixed(1)} s
            </div>
            <div className="mt-1 text-xs text-ink-3">{simulated ? 'simulated' : 'usually about 5 s'}</div>
          </div>
        )}
      </div>
      {tools.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-1.5 pl-11" aria-label="Actions being signed">
          {tools.map((t) => (
            <motion.li
              key={t}
              initial={reduce ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: .15 }}
            >
              <Badge size="sm" color={color} dashed icon={<Check />}>
                {toolLabel(t)}
              </Badge>
            </motion.li>
          ))}
        </ul>
      )}
      <div className="skeleton mt-4 h-1 rounded-full" aria-hidden />
    </article>
  )
}

export function PlanFailedCard({ event }: { event: RunEvent }) {
  const d = rec(event.data)
  const color = 'var(--outcome-block)'
  return (
    <article role="alert" className="rounded-2xl border p-4" style={{ borderColor: tint(color, 50), background: tint(color, 8) }}>
      <div className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg" style={{ color, background: tint(color, 16) }}>
          <Ban className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold leading-snug text-ink">{event.title || 'The plan could not be signed'}</h3>
          <p className="mt-0.5 text-[13px] leading-relaxed text-ink-2">{event.detail || str(d.error) || 'No agent step was taken.'}</p>
        </div>
      </div>
    </article>
  )
}

export function LooseDecision({ decision }: { decision: Decision }) {
  return <DecisionCard decision={decision} />
}
