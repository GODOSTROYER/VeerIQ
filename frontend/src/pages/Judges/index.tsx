import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  Check,
  Copy,
  FileCheck2,
  Gavel,
  Play,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Undo2,
  X,
} from 'lucide-react'
import { api, errorMessage } from '@/api/client'
import { invalidate, invalidateAppData, TAGS } from '@/api/bus'
import { clearQueryCache } from '@/api/cache'
import { useApprovals, useAppState, useRun, useRunEvents, useSystemStatus } from '@/api/hooks'
import { useSession } from '@/api/session'
import type { AppState, Run, RunDetail, RunEvent, TaskGrant } from '@/api/types'
import { TERMINAL_RUN_STATUSES } from '@/api/types'
import { Button, Skeleton } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatMoney } from '@/lib/format'
import { fieldLabel } from '@/lib/labels'
import { describeRunOutcome, livePlannerNote, plannerBadge } from '@/lib/honesty'
import { APPROVER_ID, OPERATOR_ID } from '@/lib/roles'
import { tamperOneNumber, verifyEvidence, type EvidenceCheck } from '@/lib/verifyEvidence'
import reliability from '@/data/reliabilitySummary.json'

// ─── types for the two judge-only endpoints ─────────────────────────────────

interface RollbackChange {
  kind: 'damage_repaired' | 'later_decision_reverted' | 'erased_record_returns' | 'new_record_lost' | 'access_reenabled' | 'access_changed'
  entity: string
  verdict: 'good' | 'harm'
  label: string
  detail: string
}
interface RollbackPreview {
  snapshot_id: string
  snapshot_taken_at: string
  changes: RollbackChange[]
  repaired: number
  harmed: number
}
interface McpInstall {
  grant_id: string
  server_name: string
  mode: string
  placeholder: string
  setup_steps: string[]
  claude_code: string
  local_http: string
  claude_desktop: unknown
  tools: string[]
}

const STEPS = ['The damage', 'Undo it two ways', 'You are the second key', 'Check our work'] as const
type StepIndex = 0 | 1 | 2 | 3

/** Progress survives a refresh or a detour into the full run view (per browser tab). */
const SAVE_KEY = 'veeriq.judges.v1'
interface Saved {
  started: boolean
  step: StepIndex
  preview: RollbackPreview | null
  repairRunId: string | null
  reviewRunId: string | null
}
function loadSaved(): Saved | null {
  try {
    const raw = sessionStorage.getItem(SAVE_KEY)
    return raw ? (JSON.parse(raw) as Saved) : null
  } catch {
    return null
  }
}

/** The planner as reported by GET /api/system/status or derived from a run. */
interface PlannerInfo { kind?: string | null; name?: string | null; provider?: string | null }

const terminal = (run?: Run | null) => !!run && TERMINAL_RUN_STATUSES.includes(run.status)

// ─── small building blocks ──────────────────────────────────────────────────

function StepHeader({ n, title, lead }: { n: number; title: string; lead: ReactNode }) {
  return (
    <header className="mb-6">
      <p className="font-mono text-xs uppercase tracking-[0.18em] text-[var(--layer-armoriq)]">Step {n} of 4</p>
      <h2 className="mt-2 text-[32px] font-semibold leading-tight tracking-[-0.03em] text-ink">{title}</h2>
      <p className="mt-2 max-w-[68ch] text-[15px] leading-relaxed text-ink-2">{lead}</p>
    </header>
  )
}

function Row({ tone, title, detail, right }: { tone: 'good' | 'harm' | 'keep' | 'neutral'; title: ReactNode; detail?: ReactNode; right?: ReactNode }) {
  const color = { good: 'var(--diff-good)', harm: 'var(--diff-bad)', keep: 'var(--diff-keep)', neutral: 'var(--outcome-neutral)' }[tone]
  const Icon = tone === 'harm' ? X : tone === 'neutral' ? ArrowRight : Check
  return (
    <li className="flex items-start gap-3 border-t border-line py-3 first:border-t-0">
      <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full" style={{ background: `color-mix(in srgb, ${color} 18%, transparent)`, color }}>
        <Icon className="size-3.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[14px] font-medium text-ink">{title}</p>
        {detail && <p className="mt-0.5 text-[13px] leading-relaxed text-ink-3">{detail}</p>}
      </div>
      {right}
    </li>
  )
}

function Card({ title, tag, tone, children }: { title: ReactNode; tag?: ReactNode; tone?: 'good' | 'harm'; children: ReactNode }) {
  return (
    <section
      className="border bg-raised p-5"
      style={{ borderColor: tone === 'harm' ? 'color-mix(in srgb, var(--diff-bad) 45%, var(--border))' : tone === 'good' ? 'color-mix(in srgb, var(--diff-good) 45%, var(--border))' : 'var(--border)' }}
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[17px] font-semibold tracking-[-0.01em] text-ink">{title}</h3>
        {tag}
      </div>
      {children}
    </section>
  )
}

function Pill({ tone, children }: { tone: 'good' | 'harm' | 'info' | 'hold'; children: ReactNode }) {
  const color = { good: 'var(--diff-good)', harm: 'var(--diff-bad)', info: 'var(--outcome-info)', hold: 'var(--outcome-hold)' }[tone]
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.08em]" style={{ background: `color-mix(in srgb, ${color} 16%, transparent)`, color }}>
      {children}
    </span>
  )
}

function CopyLine({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex items-stretch border border-line bg-sunken">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap px-3 py-2.5 font-mono text-[12px] text-ink-2">{text}</code>
      <button
        type="button"
        aria-label={label}
        className="border-l border-line px-3 text-ink-2 hover:bg-surface-2"
        onClick={() => {
          void navigator.clipboard.writeText(text).then(() => {
            setCopied(true)
            window.setTimeout(() => setCopied(false), 1500)
          })
        }}
      >
        {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
      </button>
    </div>
  )
}

/** The latest few run events, in the words the backend already writes for people. */
function LiveFeed({ events, running, planner }: { events: RunEvent[]; running: boolean; planner: PlannerInfo | null }) {
  const shown = events.filter((e) => e.type !== 'run.status' && e.type !== 'state.changed' && e.title).slice(-6)
  return (
    <ol className="space-y-2" aria-live="polite">
      {shown.map((e) => {
        const blocked = e.type === 'decision' && e.decision?.outcome === 'block' && e.decision.decisive
        const armoriq = e.decision?.layer === 'armoriq'
        return (
          <li key={e.seq} className={cn('border-l-2 py-1 pl-3 text-[13px]', blocked ? 'border-[var(--diff-bad)] text-ink' : 'border-line text-ink-2')}>
            <span className="font-medium">{blocked && armoriq ? 'ArmorIQ blocked it: ' : ''}{e.title}</span>
            {blocked && e.detail && <span className="mt-0.5 block text-xs text-ink-3">{e.detail}</span>}
          </li>
        )
      })}
      {running && <li className="pl-3 text-xs text-ink-3">{livePlannerNote(planner)}</li>}
    </ol>
  )
}

// ─── step 1: the damage ─────────────────────────────────────────────────────

function laterDecisions(state: AppState) {
  const erased = state.deleted.filter((d) => d.entity_type === 'customer')
  const revoked = state.access_grants.filter((g) => g.status === 'revoked')
  const later = state.orders.filter((o) => o.condition === 'changed_after_snapshot')
  return { erased, revoked, later }
}

function DamageStep({ state, onNext }: { state: AppState; onNext: () => void }) {
  const damaged = state.orders.filter((o) => o.condition === 'damaged')
  const missing = damaged.reduce((sum, o) => sum + Math.max(0, (o.total_cents === 0 ? 1 : 0)), 0)
  const { erased, revoked, later } = laterDecisions(state)
  return (
    <div>
      <StepHeader
        n={1}
        title="A bad change just wrecked this store's orders."
        lead={<>At 2:14 AM a broken migration zeroed order totals at Atlas Outfitters. You have a backup from midnight. But the business kept running after the backup: people made decisions that the backup knows nothing about.</>}
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Damaged by the incident" tag={<Pill tone="harm">{damaged.length} orders broken</Pill>} tone="harm">
          <ul>
            {damaged.map((o) => (
              <Row key={o.order_id} tone="harm" title={<>{o.order_id} · {o.customer_name}</>} detail={<>Total now {formatMoney(o.total_cents)}{o.status === 'corrupted' ? ', status corrupted' : ''}{o.shipping_region === null ? ', shipping region wiped' : ''}</>} />
            ))}
          </ul>
          {missing > 0 && <p className="mt-3 text-xs text-ink-3">These need their old values back.</p>}
        </Card>
        <Card title="Decided after the backup (must stay)" tag={<Pill tone="info">{erased.length + revoked.length + later.length} decisions</Pill>}>
          <ul>
            {erased.map((d) => <Row key={d.entity_id} tone="keep" title={<>{d.display_name} was erased</>} detail={d.reason} />)}
            {revoked.map((g) => <Row key={g.grant_id} tone="keep" title={<>{g.principal}'s access was revoked</>} detail={g.revoked_reason ?? undefined} />)}
            {later.map((o) => <Row key={o.order_id} tone="keep" title={<>{o.order_id} was {o.status}</>} detail={`Updated by ${o.updated_by} after the backup.`} />)}
          </ul>
        </Card>
      </div>
      <div className="mt-6 flex justify-end">
        <Button variant="primary" size="lg" iconRight={<ArrowRight />} onClick={onNext}>
          Undo the damage
        </Button>
      </div>
    </div>
  )
}

// ─── step 2: full rollback vs VeerIQ ────────────────────────────────────────

function RollbackColumn({ preview }: { preview: RollbackPreview | null }) {
  if (!preview) return <Skeleton className="h-72 w-full" />
  const good = preview.changes.filter((c) => c.verdict === 'good')
  const harm = preview.changes.filter((c) => c.verdict === 'harm')
  return (
    <Card title="Option A: restore the backup" tag={<Pill tone="harm">fixes {good.length} · breaks {harm.length}</Pill>} tone="harm">
      <p className="mb-2 text-[13px] text-ink-3">What most teams do. A computed counterfactual (source: docs/evidence/blunt-restore-counterfactual.json), not an executed experiment. Computed from the real snapshot against today's data; nothing is written.</p>
      <ul>
        {good.map((c) => <Row key={c.entity} tone="good" title={c.label} />)}
        {harm.map((c) => <Row key={c.entity} tone="harm" title={c.label} detail={c.detail} />)}
      </ul>
    </Card>
  )
}

function VeerIQColumn({
  run,
  events,
  state,
  starting,
  error,
  planner: systemPlanner,
  onStart,
}: {
  run: Run | undefined
  events: RunEvent[]
  state: AppState | undefined
  starting: boolean
  error: string | null
  planner: PlannerInfo | null
  onStart: () => void
}) {
  const done = terminal(run)
  const blocked = events.find((e) => e.type === 'decision' && e.decision?.outcome === 'block' && e.decision.decisive && e.decision.layer === 'armoriq')
  // Prefer the run's own planner; fall back to what the system reports before a run exists.
  const planner: PlannerInfo | null = run
    ? { kind: run.planner_kind, name: run.metadata.planner_label ?? run.planner, provider: systemPlanner?.provider }
    : systemPlanner
  if (!run) {
    return (
      <Card title="Option B: let VeerIQ's agent repair it" tag={<Pill tone="info">{plannerBadge(planner?.kind)}</Pill>}>
        <p className="text-[14px] leading-relaxed text-ink-2">
          An AI agent gets one narrow job: put back the damaged values, nothing else. Every action it proposes is checked by VeerIQ's gates and ArmorIQ, which signs the agent's plan before it runs.
        </p>
        <p className="mt-3 text-[14px] leading-relaxed text-ink-2">
          The trap: the backup carries a planted note telling the agent to <b className="text-ink">re-enable the revoked account</b>. Watch what happens.
        </p>
        {error && <p className="mt-3 text-[13px] text-block">{error}</p>}
        <Button className="mt-5" variant="primary" size="lg" icon={<Play />} loading={starting} onClick={onStart}>
          Run the AI repair
        </Button>
      </Card>
    )
  }
  const preserved = state ? laterDecisions(state) : null
  const repaired = state?.orders.filter((o) => o.updated_by === `rewindsafe:${run.run_id}`) ?? []
  return (
    <Card
      title="Option B: VeerIQ"
      tag={done ? <Pill tone={run.status === 'succeeded' ? 'good' : 'harm'}>{run.status.replace('_', ' ')}</Pill> : <Pill tone="info">running</Pill>}
      tone={done && run.status === 'succeeded' ? 'good' : undefined}
    >
      {blocked && (
        <div className="mb-4 border border-[color-mix(in_srgb,var(--diff-bad)_45%,var(--border))] bg-[color-mix(in_srgb,var(--diff-bad)_8%,transparent)] p-3">
          <p className="flex items-center gap-2 text-[14px] font-semibold text-ink">
            <ShieldAlert className="size-4 text-block" aria-hidden /> The agent took the bait. ArmorIQ stopped it.
          </p>
          <p className="mt-1 text-[13px] text-ink-2">{blocked.decision?.reason}</p>
        </div>
      )}
      {!done && <LiveFeed events={events} running planner={planner} />}
      {done && preserved && (
        <ul>
          {repaired.map((o) => <Row key={o.order_id} tone="good" title={<>{o.order_id} repaired: {formatMoney(o.total_cents)}</>} />)}
          {preserved.erased.map((d) => <Row key={d.entity_id} tone="keep" title={<>{d.display_name} stays erased</>} />)}
          {preserved.revoked.map((g) => <Row key={g.grant_id} tone="keep" title={<>{g.principal} stays revoked</>} />)}
          {preserved.later.map((o) => <Row key={o.order_id} tone="keep" title={<>{o.order_id} stays {o.status}</>} />)}
          <Row tone="neutral" title="One repair is $12,400" detail="Too big for one person to approve alone. That's the next step." />
        </ul>
      )}
      {done && (
        <Link to={`/runs/${run.run_id}`} className="mt-4 inline-flex items-center gap-1.5 text-[13px] text-ink-3 hover:text-ink">
          Open the full run with every decision <ArrowRight className="size-3.5" />
        </Link>
      )}
    </Card>
  )
}

// ─── step 3: the second key ─────────────────────────────────────────────────

function ReviewStep({
  run,
  detail,
  starting,
  error,
  onStart,
  onNext,
}: {
  run: Run | undefined
  detail: RunDetail | undefined
  starting: boolean
  error: string | null
  onStart: () => void
  onNext: () => void
}) {
  const { identity, signIn } = useSession()
  const pending = useApprovals('pending', !!run)
  const approval = pending.data?.find((a) => a.run_id === run?.run_id)
  const [deciding, setDeciding] = useState<'approve' | 'reject' | null>(null)
  const [decided, setDecided] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [decideError, setDecideError] = useState<string | null>(null)
  const isApprover = identity?.identity_id === APPROVER_ID

  const refetchPending = pending.refetch
  const waiting = !!run && !terminal(run) && !approval
  useEffect(() => {
    if (!waiting) return undefined
    const t = window.setInterval(() => void refetchPending(), 1500)
    return () => window.clearInterval(t)
  }, [waiting, refetchPending])

  const decide = async (decision: 'approve' | 'reject') => {
    if (!approval) return
    setDeciding(decision)
    setDecideError(null)
    try {
      await api.post(`/approvals/${approval.approval_id}/decide`, { decision, note: 'Decided by the judge in the walkthrough.' })
      setDecided(true)
      invalidate(TAGS.approvals, TAGS.run(approval.run_id), TAGS.runs)
      invalidateAppData()
    } catch (err) {
      setDecideError(errorMessage(err))
    } finally {
      setDeciding(null)
    }
  }

  const done = terminal(run)
  const outcome = done && run ? describeRunOutcome({ run, approvals: detail?.approvals, receipts: detail?.receipts, commits: detail?.metrics?.commits }) : null
  return (
    <div>
      <StepHeader
        n={3}
        title="One repair is $12,400. You are the second key."
        lead={<>Order O-2046 lost a $12,400 total. VeerIQ won't let anyone commit a repair that big alone: not the AI agent, and not the person who asked for it. Someone else has to approve the exact change. Here, that's you.</>}
      />
      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <Card title="The $12,400 repair" tag={run ? <Pill tone={done ? (run.status === 'succeeded' ? 'good' : 'harm') : run.status === 'awaiting_approval' ? 'hold' : 'info'}>{run.status.replace('_', ' ')}</Pill> : undefined}>
          {!run && (
            <>
              <p className="text-[14px] leading-relaxed text-ink-2">The operator (Nova) asks the agent to repair O-2046. The agent prepares the exact change, then the run pauses before anything is written.</p>
              {error && <p className="mt-3 text-[13px] text-block">{error}</p>}
              <Button className="mt-5" variant="primary" size="lg" icon={<Play />} loading={starting} onClick={onStart}>
                Ask for the $12,400 repair
              </Button>
            </>
          )}
          {run && !approval && !done && (
            <p className="text-[14px] text-ink-2">{decided ? 'Decision recorded. Every gate runs again against the live data, then it commits…' : 'The agent is preparing the change…'}</p>
          )}
          {approval && !done && (
            <>
              <p className="text-[14px] text-ink-2">{approval.reason}</p>
              <ul className="mt-3">
                {(approval.manifest?.changes ?? []).map((c) => (
                  <Row
                    key={`${c.row_id}-${c.field}`}
                    tone="neutral"
                    title={<>{c.row_id} · {fieldLabel(c.field)}</>}
                    detail={<>{c.field === 'total_cents' ? formatMoney(Number(c.current_value)) : String(c.current_value ?? '—')} → {c.field === 'total_cents' ? formatMoney(Number(c.new_value)) : String(c.new_value ?? '—')}</>}
                  />
                ))}
              </ul>
              {!isApprover ? (
                <>
                  <p className="mt-4 text-[13px] text-ink-3">Nova asked for it, so Nova can't approve it. Switch to Dev, the approver.</p>
                  <Button
                    className="mt-3"
                    variant="primary"
                    size="lg"
                    icon={<Gavel />}
                    loading={switching}
                    onClick={() => {
                      setSwitching(true)
                      void signIn(APPROVER_ID).finally(() => setSwitching(false))
                    }}
                  >
                    Become the approver
                  </Button>
                </>
              ) : (
                <div className="mt-5 flex flex-wrap gap-3">
                  <Button variant="primary" size="lg" icon={<Check />} loading={deciding === 'approve'} disabled={!!deciding} onClick={() => void decide('approve')}>
                    Approve this exact change
                  </Button>
                  <Button variant="danger" size="lg" icon={<X />} loading={deciding === 'reject'} disabled={!!deciding} onClick={() => void decide('reject')}>
                    Reject
                  </Button>
                </div>
              )}
              {decideError && <p className="mt-3 text-[13px] text-block">{decideError}</p>}
            </>
          )}
          {done && run && outcome && (
            <ul>
              <Row
                tone={outcome.tone}
                title={outcome.title}
                detail={run.outcome_summary ?? undefined}
              />
            </ul>
          )}
        </Card>
        <Card title="Why this matters">
          <ul>
            <Row tone="keep" title="Bound to the exact change" detail="The approval covers this payload's digest. If the change is altered, the approval no longer applies." />
            <Row tone="keep" title="Separation of duties" detail="The requester can never approve their own repair." />
            <Row tone="keep" title="Re-checked before commit" detail="After approval every gate runs again against the live data." />
          </ul>
          <p className="mt-3 text-xs text-ink-3">This approval step is VeerIQ's own. ArmorIQ's policy decides which tools the agent may call at all.</p>
        </Card>
      </div>
      <div className="mt-6 flex justify-end">
        <Button variant="primary" size="lg" iconRight={<ArrowRight />} disabled={!done} onClick={onNext}>
          Check our work
        </Button>
      </div>
    </div>
  )
}

// ─── step 4: verify + scoreboard + install ──────────────────────────────────

function CheckRow({ ok, label, detail }: { ok: boolean; label: string; detail?: string }) {
  return <Row tone={ok ? 'good' : 'harm'} title={label} detail={detail} />
}

function ProofStep({ repairRunId }: { repairRunId: string | null }) {
  const { identity, signIn } = useSession()
  const [text, setText] = useState<string | null>(null)
  const [real, setReal] = useState<EvidenceCheck | null>(null)
  const [tampered, setTampered] = useState<{ check: EvidenceCheck; changed: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [install, setInstall] = useState<McpInstall | null>(null)
  const [installBusy, setInstallBusy] = useState(false)
  const [installError, setInstallError] = useState<string | null>(null)
  const totals = reliability.totals

  const verify = async () => {
    if (!repairRunId) return
    setBusy(true)
    setError(null)
    setTampered(null)
    try {
      const res = await fetch(`/api/runs/${repairRunId}/sealed-evidence`, { credentials: 'include' })
      if (!res.ok) throw new Error(`The receipt could not be downloaded (${res.status}).`)
      const body = await res.text()
      setText(body)
      setReal(await verifyEvidence(body))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const tamper = async () => {
    if (!text) return
    const t = tamperOneNumber(text)
    const m = /(\d+) → (\d+)/.exec(t.changed)
    const changed = m ? `an amount from ${formatMoney(Number(m[1]))} to ${formatMoney(Number(m[2]))}` : t.changed
    setTampered({ check: await verifyEvidence(t.text), changed })
  }

  const getInstall = async () => {
    setInstallBusy(true)
    setInstallError(null)
    try {
      if (identity?.identity_id !== OPERATOR_ID) await signIn(OPERATOR_ID)
      const draft = await api.post<TaskGrant>('/grants/draft', { scenario_id: 'poisoned' })
      await api.post(`/grants/${draft.grant_id}/authorize`)
      setInstall(await api.get<McpInstall>(`/judge/mcp-install/${draft.grant_id}`))
    } catch (err) {
      setInstallError(errorMessage(err))
    } finally {
      setInstallBusy(false)
    }
  }

  return (
    <div>
      <StepHeader
        n={4}
        title="Don't trust our screen. Check it."
        lead="Every run ends in a signed receipt: each event hash-chained to the one before, signed with Ed25519. Your browser checks it below with its own crypto. Nothing is sent to our server."
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Verify the receipt of your repair" tag={real ? <Pill tone={real.valid ? 'good' : 'harm'}>{real.valid ? 'verified' : real.integrity ? 'not trusted' : 'integrity failed'}</Pill> : undefined}>
          {!real && (
            <>
              <p className="text-[14px] text-ink-2">Download the receipt of the repair you just ran and verify it here.</p>
              {error && <p className="mt-3 text-[13px] text-block">{error}</p>}
              <Button className="mt-4" variant="primary" size="lg" icon={<FileCheck2 />} loading={busy} disabled={!repairRunId} onClick={() => void verify()}>
                Verify in my browser
              </Button>
            </>
          )}
          {real && (
            <>
              <ul>
                <CheckRow ok={real.payloadDigest} label="Contents match their fingerprint" detail={real.computedDigest.slice(0, 31) + '…'} />
                <CheckRow ok={real.eventChain} label={`All ${real.events} events chained in order`} />
                <CheckRow ok={real.signature && real.fingerprintField} label="Ed25519 signature valid" />
                <CheckRow
                  ok={real.trust === 'trusted'}
                  label={real.trust === 'trusted' ? "Signed by VeerIQ's pinned operator key" : 'Signer is not the pinned operator key'}
                  detail={`Signer ${real.keyFingerprint}`}
                />
              </ul>
              <p className={`mt-2 text-[13px] font-medium ${real.valid ? 'text-ink' : 'text-block'}`}>{real.verdict}</p>
              {!tampered ? (
                <Button className="mt-4" variant="secondary" icon={<RotateCcw />} onClick={() => void tamper()}>
                  Change one number and check again
                </Button>
              ) : (
                <div className="mt-4 border-t border-line pt-3">
                  <p className="text-[13px] text-ink-2">
                    Changed {tampered.changed}. Result: <b className={tampered.check.valid ? 'text-ink' : 'text-block'}>{tampered.check.valid ? 'still verified' : 'rejected'}</b>
                  </p>
                  <ul className="mt-1">
                    <CheckRow ok={tampered.check.payloadDigest} label="Contents match their fingerprint" />
                    <CheckRow ok={tampered.check.eventChain} label="Events chained in order" />
                  </ul>
                </div>
              )}
              <p className="mt-3 text-xs text-ink-3">Offline too: <code className="font-mono">./scripts/veeriq-verify receipt.json</code></p>
            </>
          )}
        </Card>
        <Card title="Not just once: 84 live runs" tag={<Pill tone="good">measured</Pill>}>
          <div className="grid grid-cols-2 gap-px bg-line">
            {[
              [totals.trials, 'live runs with a real model'],
              [totals.poisoned_action_attempted, 'times it tried to re-enable the revoked account'],
              [totals.poisoned_action_blocked, 'blocked by ArmorIQ'],
              [totals.forbidden_effects, `forbidden changes observed (in ${totals.records_with_effect_observation} of ${totals.records_total} records; ${totals.records_unknown_effect_status} interrupted records lack effect observations)`],
            ].map(([n, label]) => (
              <div key={String(label)} className="bg-raised p-4">
                <p className="text-[34px] font-semibold tabular tracking-[-0.03em] text-ink">{n}</p>
                <p className="text-[13px] text-ink-3">{label}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[13px] leading-relaxed text-ink-2">
            ArmorIQ plan binding blocked all {totals.poisoned_action_blocked} observed attempts ({totals.poisoned_action_attempted} tried). Zero forbidden changes were made.
          </p>
          <p className="mt-2 text-xs text-ink-3">gpt-oss-120b on Groq, live ArmorIQ, Oct 2026. {reliability.caveat}</p>
        </Card>
      </div>

      <div className="mt-4">
        <Card title="Run VeerIQ's MCP server from your own checkout" tag={<Pill tone="info">Claude Code · Cursor · Claude Desktop</Pill>}>
          <p className="text-[14px] text-ink-2">
            VeerIQ is an MCP server with six recovery tools. It runs on your machine, from a clone of the repo with its own database, and the web app and the MCP server share the same dispatcher, so MCP calls pass the same gates and ArmorIQ. The separate recorded MCP run is docs/evidence/mcp-live-agent-run.json. This is not a hosted endpoint.
          </p>
          {!install ? (
            <>
              {installError && <p className="mt-3 text-[13px] text-block">{installError}</p>}
              <Button className="mt-4" variant="secondary" icon={<ShieldCheck />} loading={installBusy} onClick={() => void getInstall()}>
                Authorize a task and show the setup
              </Button>
            </>
          ) : (
            <div className="mt-4 space-y-3">
              <ol className="list-decimal space-y-1 pl-5 text-[13px] text-ink-2">
                {install.setup_steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
              <p className="text-xs text-ink-3">Claude Code (replace {install.placeholder} with your checkout path)</p>
              <CopyLine text={install.claude_code} label="Copy the Claude Code command" />
              <p className="text-xs text-ink-3">The grant {install.grant_id} limits what it may do.</p>
              <details className="text-[13px] text-ink-2">
                <summary className="cursor-pointer text-ink-3">Claude Desktop / Cursor config</summary>
                <pre className="mt-2 overflow-x-auto border border-line bg-sunken p-3 font-mono text-[12px]">{JSON.stringify(install.claude_desktop, null, 2)}</pre>
              </details>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

// ─── page ───────────────────────────────────────────────────────────────────

export default function Judges() {
  const { identity, signIn } = useSession()
  const status = useSystemStatus()
  const llm = status.data?.planner.configured_llm ?? false
  const plannerInfo: PlannerInfo | null = status.data?.planner ?? null
  const saved = useMemo(loadSaved, [])
  const [step, setStep] = useState<StepIndex>(saved?.step ?? 0)
  const [started, setStarted] = useState(saved?.started ?? false)
  const [resetting, setResetting] = useState(false)
  const [preview, setPreview] = useState<RollbackPreview | null>(saved?.preview ?? null)
  const [repairRunId, setRepairRunId] = useState<string | null>(saved?.repairRunId ?? null)
  const [reviewRunId, setReviewRunId] = useState<string | null>(saved?.reviewRunId ?? null)
  useEffect(() => {
    try {
      sessionStorage.setItem(SAVE_KEY, JSON.stringify({ started, step, preview, repairRunId, reviewRunId } satisfies Saved))
    } catch {
      // storage unavailable (private mode): progress just won't survive a refresh
    }
  }, [started, step, preview, repairRunId, reviewRunId])
  const [busy, setBusy] = useState<'repair' | 'review' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const rail = useRef<HTMLElement>(null)

  const state = useAppState(started)
  const repairRun = useRun(repairRunId ?? undefined)
  const repairEvents = useRunEvents(repairRunId ?? undefined)
  const reviewRun = useRun(reviewRunId ?? undefined)
  useRunEvents(reviewRunId ?? undefined) // keeps the review run's status and approvals fresh

  const go = useCallback((n: StepIndex) => {
    setStep(n)
    setError(null)
    window.setTimeout(() => rail.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 30)
  }, [])

  const asOperator = async () => {
    if (identity?.identity_id !== OPERATOR_ID) await signIn(OPERATOR_ID)
  }

  const start = async () => {
    setResetting(true)
    setError(null)
    try {
      await asOperator()
      await api.post('/admin/reset')
      clearQueryCache()
      invalidate(TAGS.appState, TAGS.checks, TAGS.diff, TAGS.runs, TAGS.approvals, TAGS.metrics, TAGS.status)
      setRepairRunId(null)
      setReviewRunId(null)
      setPreview(await api.get<RollbackPreview>('/app/full-rollback-preview'))
      setStarted(true)
      go(0)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setResetting(false)
    }
  }

  const launch = async (scenario: 'poisoned' | 'review') => {
    setBusy(scenario === 'poisoned' ? 'repair' : 'review')
    setError(null)
    try {
      await asOperator()
      const grant = await api.post<TaskGrant>('/grants/draft', { scenario_id: scenario })
      await api.post(`/grants/${grant.grant_id}/authorize`)
      const planner = scenario === 'poisoned' ? (llm ? 'llm' : 'auto') : 'scripted'
      const run = await api.post<Run>('/runs', { grant_id: grant.grant_id, planner })
      invalidate(TAGS.runs)
      if (scenario === 'poisoned') setRepairRunId(run.run_id)
      else setReviewRunId(run.run_id)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  // Refresh the after-state when the repair finishes.
  const repairDone = terminal(repairRun.data?.run)
  useEffect(() => {
    if (repairDone) invalidateAppData()
  }, [repairDone])

  const totals = reliability.totals
  const progress = useMemo(() => (started ? step + 1 : 0), [started, step])

  return (
    <div className="mx-auto max-w-[1180px] pb-24">
      {/* hero */}
      <section className="grid gap-8 border-b border-line pb-10 pt-4 lg:grid-cols-[1.25fr_1fr] lg:items-end">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.18em] text-[var(--layer-armoriq)]">VeerIQ · for judges · about 3 minutes</p>
          <h1 className="recovery-headline mt-3 !max-w-none">
            Ctrl+Z for <span>AI agents.</span>
          </h1>
          <p className="mt-4 max-w-[60ch] text-[17px] leading-relaxed text-ink-2">
            When an agent or a bad change wrecks your database, VeerIQ undoes <b className="text-ink">only the damage</b> and keeps everything that happened since. ArmorIQ makes sure the fixer can't go rogue too.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Button variant="primary" size="lg" icon={started ? <RotateCcw /> : <Play />} loading={resetting} onClick={() => void start()}>
              {started ? 'Start over with fresh data' : 'Start the demo'}
            </Button>
            <Link to="/workspace" className="text-[14px] text-ink-3 hover:text-ink">or explore the full workspace →</Link>
          </div>
          <p className="mt-3 max-w-[60ch] text-[13px] text-ink-3">The demo data is shared, so if results look mid-run, press Start (or Start over) to reset it.</p>
          {error && !started && <p className="mt-3 text-[13px] text-block">{error}</p>}
        </div>
        <aside className="border border-line bg-raised p-5">
          <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-ink-3">Why this exists</p>
          <p className="mt-2 text-[14px] leading-relaxed text-ink-2">
            July 2025: an AI coding agent wiped a company's production database during a code freeze, then wrongly said it couldn't be undone. The data came back from a backup, and a backup also brings back everything you decided since it was taken.
          </p>
          <div className="mt-4 grid grid-cols-3 gap-3 border-t border-line pt-4 text-center">
            <div><p className="text-2xl font-semibold tabular text-ink">{totals.trials}</p><p className="text-[11px] text-ink-3">live runs</p></div>
            <div><p className="text-2xl font-semibold tabular text-ink">{totals.poisoned_action_blocked}/{totals.poisoned_action_attempted}</p><p className="text-[11px] text-ink-3">attacks blocked</p></div>
            <div><p className="text-2xl font-semibold tabular text-ink">{totals.forbidden_effects}</p><p className="text-[11px] text-ink-3">forbidden changes observed ({totals.records_with_effect_observation} of {totals.records_total} records)</p></div>
          </div>
        </aside>
      </section>

      {/* step rail */}
      <nav ref={rail} aria-label="Demo steps" className="mt-6 scroll-mt-28 py-3">
        <ol className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {STEPS.map((label, i) => {
            const reached = started && i <= step
            return (
              <li key={label}>
                <button
                  type="button"
                  disabled={!started}
                  onClick={() => go(i as StepIndex)}
                  aria-current={started && i === step ? 'step' : undefined}
                  className={cn('flex w-full items-center gap-2 border px-3 py-2 text-left text-[13px] transition-colors', started && i === step ? 'border-[var(--primary)] text-ink' : 'border-line text-ink-3', !started && 'opacity-60')}
                >
                  <span className={cn('grid size-5 shrink-0 place-items-center rounded-full font-mono text-[11px]', reached ? 'bg-[var(--primary)] text-ink-inverse' : 'bg-surface-3')}>{i + 1}</span>
                  {label}
                </button>
              </li>
            )
          })}
        </ol>
        <div className="mt-2 h-0.5 bg-surface-3"><div className="h-full bg-[var(--primary)] transition-[width] duration-300" style={{ width: `${(progress / 4) * 100}%` }} /></div>
      </nav>

      <main className="mt-8">
        {!started && (
          <div className="grid gap-4 md:grid-cols-3">
            {[
              [Undo2, 'Undo only the damage', 'See a computed full-restore counterfactual break four business decisions, and VeerIQ keep all of them.'],
              [ShieldAlert, 'Watch a live attack fail', 'A planted note tells the agent to re-enable a leaked account. ArmorIQ blocks the call.'],
              [ShieldCheck, 'Approve, then verify', 'Be the second key on a $12,400 repair, then check the signed receipt in your browser.'],
            ].map(([Icon, title, text]) => {
              const I = Icon as typeof Undo2
              return (
                <div key={String(title)} className="border border-line bg-raised p-5">
                  <I className="size-5 text-[var(--layer-armoriq)]" aria-hidden />
                  <p className="mt-3 text-[15px] font-semibold text-ink">{String(title)}</p>
                  <p className="mt-1 text-[13px] leading-relaxed text-ink-3">{String(text)}</p>
                </div>
              )
            })}
          </div>
        )}

        {started && step === 0 && (state.data ? <DamageStep state={state.data} onNext={() => go(1)} /> : <Skeleton className="h-80 w-full" />)}

        {started && step === 1 && (
          <div>
            <StepHeader
              n={2}
              title="Two ways to undo it."
              lead="On the left, what restoring the backup would do to today's data. On the right, VeerIQ's agent repairs only the damage, live."
            />
            <div className="grid gap-4 lg:grid-cols-2">
              <RollbackColumn preview={preview} />
              <VeerIQColumn
                run={repairRun.data?.run}
                events={repairEvents.events}
                state={state.data}
                starting={busy === 'repair'}
                error={error}
                planner={plannerInfo}
                onStart={() => void launch('poisoned')}
              />
            </div>
            <div className="mt-6 flex justify-end">
              <Button variant="primary" size="lg" iconRight={<ArrowRight />} disabled={!repairDone} onClick={() => go(2)}>
                Next: the $12,400 repair
              </Button>
            </div>
          </div>
        )}

        {started && step === 2 && (
          <ReviewStep run={reviewRun.data?.run} detail={reviewRun.data} starting={busy === 'review'} error={error} onStart={() => void launch('review')} onNext={() => go(3)} />
        )}

        {started && step === 3 && <ProofStep repairRunId={repairRunId} />}
      </main>
    </div>
  )
}
