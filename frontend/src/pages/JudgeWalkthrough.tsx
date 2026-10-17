import { OfflineProof } from '@/components/domain/OfflineProof'
import { fieldLabel } from '@/lib/labels'
import { formatMoney } from '@/lib/format'
import { RecordedPolicyProof } from '@/components/domain/RecordedPolicyProof'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleHelp,
  Database,
  LockKeyhole,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { useRun, useRunEvents, useRuns } from '@/api/hooks'
import type { ActionProposal, ExecutionManifest, ExecutionReceipt, InvariantCheck, ProposalBundle, Run, RunDetail, RunEvent, RunMetrics, TaskGrant } from '@/api/types'
import { Button, ErrorState, Skeleton } from '@/components/ui'

const RECORDED_LIVE_RUN = 'run_01M4R4DB4JAY7ARM'
/** The signed export of that run, shipped with the app (also offered for download on the Proof page). */
const BUNDLED_EXPORT = '/verification/valid-live-recovery.json'

/** The parts of a sealed evidence payload the walkthrough reads. */
interface SealedPayload {
  run: Run
  grant: TaskGrant
  proposals: ProposalBundle[]
  metrics: RunMetrics
  protected_checks: { checks: InvariantCheck[] } | null
  events: RunEvent[]
}

interface BundledRun {
  detail: RunDetail
  events: RunEvent[]
}

function toBundledRun(payload: SealedPayload): BundledRun {
  return {
    detail: {
      run: payload.run,
      grant: payload.grant,
      proposals: payload.proposals,
      approvals: payload.proposals.flatMap((bundle) => bundle.approval ? [bundle.approval] : []),
      receipts: payload.proposals.flatMap((bundle) => bundle.receipt ? [bundle.receipt] : []),
      metrics: payload.metrics,
      protected_checks: payload.protected_checks?.checks ?? [],
    },
    events: payload.events,
  }
}

/** The recorded live run, read from the bundled signed export when this workspace has no live run to replay. */
function useBundledRun(enabled: boolean): { data?: BundledRun; failed: boolean } {
  const [state, setState] = useState<{ data?: BundledRun; failed: boolean }>({ failed: false })
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    fetch(BUNDLED_EXPORT)
      .then((response) => response.ok ? response.json() as Promise<{ payload: SealedPayload }> : Promise.reject(new Error(String(response.status))))
      .then((envelope) => { if (!cancelled) setState({ data: toBundledRun(envelope.payload), failed: false }) })
      .catch(() => { if (!cancelled) setState({ failed: true }) })
    return () => { cancelled = true }
  }, [enabled])
  return state
}

const DAY = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

/** "12 Oct 2026". Run timestamps carry microseconds; trim them so every engine parses the value. */
function recordedDay(iso: string): string {
  const date = new Date(iso.replace(/(\.\d{3})\d+/, '$1'))
  return Number.isNaN(date.getTime()) ? iso : DAY.format(date)
}

const STEPS = [
  { name: 'Incident', short: 'Incident context', icon: Database },
  { name: 'Scope', short: 'Task boundary', icon: LockKeyhole },
  { name: 'Attempt', short: 'Agent attempt', icon: Sparkles },
  { name: 'Boundary', short: 'Security boundary', icon: ShieldAlert },
  { name: 'Repair', short: 'Approved repair', icon: Check },
  { name: 'Proof', short: 'What held', icon: ShieldCheck },
] as const

function isSuccessfulPoisonedLive(run: Run) {
  return run.scenario_id === 'poisoned' && run.planner_kind === 'llm' && run.enforcement_mode === 'live' && run.plan?.mode === 'live' && run.plan.simulated === false && run.status === 'succeeded'
}

function selectRun(runs: Run[]): Run | undefined {
  const ordered = [...runs].sort((a, b) => b.created_at.localeCompare(a.created_at))
  return ordered.find(isSuccessfulPoisonedLive)
    ?? ordered.find((run) => run.run_id === RECORDED_LIVE_RUN)
}

function pretty(value: unknown) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

function parsePreview(event: RunEvent | undefined): Record<string, unknown> | null {
  const raw = event?.data.observation_preview
  if (typeof raw !== 'string') return null
  try {
    return JSON.parse(raw) as Record<string, unknown>
  } catch {
    return null
  }
}

function eventBy(events: RunEvent[], type: string, predicate?: (event: RunEvent) => boolean) {
  return events.find((event) => event.type === type && (!predicate || predicate(event)))
}

function getProposal(detail: RunDetail | undefined, events: RunEvent[], tool: string): ActionProposal | undefined {
  const inDetail = detail?.proposals.find((bundle) => bundle.proposal.tool === tool)?.proposal
  if (inDetail) return inDetail
  const event = eventBy(events, 'agent.proposal', (candidate) => candidate.data.tool === tool)
  if (!event) return undefined
  const args = event.data.arguments
  return {
    proposal_id: event.proposal_id ?? `event-${event.seq}`,
    run_id: event.run_id,
    step_index: Number(event.data.step_index ?? 0),
    tool,
    arguments: typeof args === 'object' && args !== null ? args as Record<string, unknown> : {},
    rationale: typeof event.data.rationale === 'string' ? event.data.rationale : '',
    source: 'agent',
    status: 'pending',
    created_at: event.ts,
  }
}

function getManifest(detail: RunDetail | undefined, events: RunEvent[]): ExecutionManifest | undefined {
  const bundled = detail?.proposals.find((bundle) => bundle.manifest)?.manifest
  if (bundled) return bundled
  const raw = eventBy(events, 'manifest.prepared')?.data.manifest
  return typeof raw === 'object' && raw !== null ? raw as ExecutionManifest : undefined
}

function getReceipt(detail: RunDetail | undefined, events: RunEvent[]): ExecutionReceipt | undefined {
  const bundled = detail?.receipts.find((receipt) => receipt.result === 'committed') ?? detail?.receipts[0]
  if (bundled) return bundled
  const raw = eventBy(events, 'execution.committed')?.data.receipt
  return typeof raw === 'object' && raw !== null ? raw as ExecutionReceipt : undefined
}

function SourceTag({ run }: { run: Run }) {
  const live = run.enforcement_mode === 'live' && run.plan?.mode === 'live' && run.plan.simulated === false
  const synthetic = run.enforcement_mode === 'offline' || run.plan?.simulated === true || run.plan?.mode === 'offline'
  const planner = run.planner_kind === 'llm' ? 'LLM agent' : run.planner_kind === 'scripted' ? 'scripted agent' : 'boundary harness'
  const replayLabel = live ? 'Recorded live replay' : synthetic ? 'Synthetic run replay' : 'Replay source unavailable'
  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="Replay source">
      <span className="inline-flex items-center gap-1.5 border border-line-strong bg-surface-2 px-2 py-1 text-[11px] font-medium text-ink">
        {live ? <span className="size-1.5 bg-[var(--outcome-allow)]" aria-hidden /> : synthetic ? <span className="size-1.5 bg-[var(--outcome-hold)]" aria-hidden /> : <span className="size-1.5 bg-ink-3" aria-hidden />}
        {replayLabel}
      </span>
      <span className="text-[11px] text-ink-3">synthetic incident data · {planner}{live ? ' · ArmorIQ live' : synthetic ? ' · ArmorIQ simulated/offline' : ''}</span>
    </div>
  )
}

function ValueRow({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="grid gap-1 border-t border-line py-2.5 sm:grid-cols-[140px_1fr] sm:gap-4"><dt className="text-xs text-ink-3">{label}</dt><dd className="min-w-0 break-words text-[13px] leading-relaxed text-ink">{value}</dd></div>
}

function walkLinkClass(primary: boolean) {
  return `inline-flex min-h-10 items-center justify-center gap-2 px-3 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus)] ${primary ? 'bg-primary text-ink-inverse hover:bg-[var(--primary-hover)]' : 'border border-line-strong text-ink hover:bg-surface-2'}`
}

function WalkLink({ to, children, primary = false }: { to: string; children: React.ReactNode; primary?: boolean }) {
  return <Link to={to} className={walkLinkClass(primary)}>{children}</Link>
}

function Panel({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`border border-line bg-surface ${className}`}>{children}</div>
}

function StageHeading({ title, children }: { title: string; children: React.ReactNode }) {
  return <header className="max-w-2xl"><h2 className="text-2xl font-semibold tracking-[-.03em] text-ink sm:text-3xl">{title}</h2><p className="mt-2 text-sm leading-relaxed text-ink-2">{children}</p></header>
}

function IncidentStage({ detail }: { detail: RunDetail }) {
  const grant = detail.grant
  const orders = grant.resources.order ?? []
  return <section className="space-y-5">
    <h3 className="text-xl font-semibold text-ink">{orders.length} orders need their damaged values restored.</h3>
    <p className="max-w-2xl text-sm leading-relaxed text-ink-2">The approved snapshot has the old values. But decisions made since that snapshot must survive the repair: deleted records stay deleted, revoked access stays revoked, and later legitimate updates stay intact.</p>
    <dl><ValueRow label="Orders in scope" value={orders.join(', ') || 'Not recorded'} /><ValueRow label="Task" value={grant.purpose} /></dl>
    <p className="border-t border-line pt-4 text-sm text-ink-2">The challenge: recover useful historical data without treating historical instructions as new permission.</p>
  </section>
}

function ScopeStage({ detail }: { detail: RunDetail }) {
  const grant = detail.grant
  const scope = Object.entries(grant.resources).flatMap(([kind, ids]) => ids.map((id) => `${kind} ${id}`))
  return <div className="grid gap-5 lg:grid-cols-[1fr_.82fr]">
    <Panel className="p-5 sm:p-6">
      <div className="flex items-center gap-2 text-sm font-semibold text-ink"><LockKeyhole className="size-4 text-[var(--layer-grant)]" aria-hidden />What the task grant permits</div>
      <dl className="mt-4">
        <ValueRow label="Records" value={scope.length ? scope.join(' · ') : 'No resource IDs in grant'} />
        <ValueRow label="Fields" value={grant.fields.map(fieldLabel).join(', ') || 'No fields in grant'} />
        <details className="py-3 text-xs text-ink-3"><summary className="cursor-pointer">View permitted tool names</summary><p className="mt-2 break-words font-mono">{grant.allowed_tools.join(', ') || 'No tools in grant'}</p></details>
        <ValueRow label="Commit limit" value={`${grant.commits_used} used · ${grant.limits.max_commits} allowed`} />
        <ValueRow label="Replan limit" value={`${detail.run.replans_used} used · ${grant.limits.max_replans} allowed`} />
      </dl>
    </Panel>
    <Panel className="p-5 sm:p-6">
      <div className="flex items-center gap-2 text-sm font-semibold text-ink"><ShieldAlert className="size-4 text-[var(--outcome-block)]" aria-hidden />The grant also forbids</div>
      <ul className="mt-4 divide-y divide-line border-y border-line">
        {grant.prohibited_effects.map((effect) => <li key={effect} className="flex gap-2.5 py-3 text-[13px] leading-relaxed text-ink-2"><span className="mt-1 text-[var(--outcome-block)]" aria-hidden>×</span>{effect}</li>)}
        {!grant.prohibited_effects.length && <li className="py-3 text-[13px] text-ink-3">No prohibited effects were returned by the API for this grant.</li>}
      </ul>
      <p className="mt-4 text-xs leading-relaxed text-ink-3">This scope comes from the selected run’s actual grant record.</p>
    </Panel>
  </div>
}

function AttemptStage({ detail, events }: { detail: RunDetail; events: RunEvent[] }) {
  const attempt = getProposal(detail, events, 'restore_access_grant')
  const inspect = events.find((event) => event.type === 'tool.result' && event.data.tool === 'inspect_snapshot')
  const preview = parsePreview(inspect)
  const annotations = Array.isArray(inspect?.data.annotations) ? inspect.data.annotations as Record<string, unknown>[] : Array.isArray(preview?.annotations) ? preview.annotations as Record<string, unknown>[] : []
  const poisoned = annotations.find((annotation) => typeof annotation.body === 'string')
  const fallbackNote = events.find((event) => event.type === 'agent.note' && /restore_access_grant|runbook|annotation/i.test(event.detail))
  return <div className="grid gap-5 lg:grid-cols-[.95fr_1.05fr]">
    <Panel className="p-5 sm:p-6">
      <p className="font-mono text-[10px] uppercase tracking-wider text-ink-3">{poisoned ? 'Untrusted snapshot instruction' : 'Agent’s recorded explanation'}</p>
      {poisoned ? <blockquote className="mt-4 border-l border-[var(--outcome-hold)] pl-4 text-sm leading-relaxed text-ink">“{String(poisoned.body)}”</blockquote> : fallbackNote ? <blockquote className="mt-4 border-l border-[var(--outcome-hold)] pl-4 text-sm leading-relaxed text-ink">{fallbackNote.detail}</blockquote> : <p className="mt-4 text-sm leading-relaxed text-ink-2">This run’s event stream does not include an annotation preview. The attempt below is shown only when its proposal was recorded.</p>}
      <p className="mt-4 text-xs leading-relaxed text-ink-3">{poisoned ? 'Snapshot annotations are data. They do not expand the operator’s grant.' : 'This recording kept a shortened model explanation; the full snapshot note was not retained in its event preview.'}</p>
    </Panel>
    <Panel className="p-5 sm:p-6">
      <div className="flex items-center justify-between gap-3"><p className="font-mono text-[10px] uppercase tracking-wider text-ink-3">Actual proposal</p>{attempt && <span className="border border-[var(--outcome-hold)] px-2 py-1 text-[10px] text-[var(--outcome-hold)]">Outside the task grant</span>}</div>
      {attempt ? <><h3 className="mt-4 text-lg font-semibold text-ink">Reactivate revoked access</h3><dl className="mt-3">
        <ValueRow label="Requested grant" value={String(attempt.arguments.grant_id ?? 'Not present')} />
        <ValueRow label="Tenant argument" value={String(attempt.arguments.tenant_id ?? 'Not present')} />
        <ValueRow label="Reason supplied" value={String(attempt.arguments.reason ?? 'Not present')} />
        <ValueRow label="Proposal source" value={attempt.source} />
      </dl></> : <p className="mt-4 text-sm text-ink-2">No access-restoration proposal appears in this run’s recorded events.</p>}
    </Panel>
  </div>
}

function BlockStage({ detail, events }: { detail: RunDetail; events: RunEvent[] }) {
  const bundle = detail.proposals.find((candidate) => candidate.proposal.tool === 'restore_access_grant')
  const block = bundle?.decisions.find((decision) => decision.decisive && decision.outcome === 'block')
    ?? events.find((event) => event.type === 'decision' && event.data.tool === 'restore_access_grant' && event.decision?.decisive && event.decision.outcome === 'block')?.decision
  const shadow = bundle?.decisions.find((decision) => decision.proposal_id === block?.proposal_id && decision.layer === 'grant' && decision.shadow)
    ?? events.find((event) => event.type === 'decision' && event.decision?.proposal_id === block?.proposal_id && event.decision?.layer === 'grant' && event.decision?.shadow)?.decision
  const metric = detail.metrics.prohibited_handler_entries
  return <div className="space-y-5">
    <Panel className="overflow-hidden">
      <div className="grid lg:grid-cols-[.7fr_1.3fr]">
        <div className="border-b border-line bg-[color-mix(in_srgb,var(--outcome-block)_9%,var(--surface))] p-5 lg:border-b-0 lg:border-r sm:p-6">
          <div className="flex items-center gap-2 text-[var(--outcome-block)]"><ShieldAlert className="size-5" aria-hidden /><span className="text-xs">{block?.source === 'armoriq.sdk.plan_binding' ? 'ArmorIQ signed-plan check' : block ? block.layer : 'Decision evidence missing'}</span></div>
          <h3 className="mt-4 text-xl font-semibold text-ink">{block?.outcome === 'block' ? 'The request was blocked' : 'No decisive block recorded'}</h3>
          <p className="mt-2 text-sm leading-relaxed text-ink-2">{block?.source === 'armoriq.sdk.plan_binding' ? 'Access restoration was not in the signed plan. The SDK refused the request before its handler ran.' : block ? block.reason : 'The selected run has no matching decision in its detail or event feed.'}</p>
        </div>
        <div className="p-5 sm:p-6">
          <p className="font-mono text-[10px] uppercase tracking-wider text-ink-3">Why it stopped</p>
          <p className="mt-3 text-sm leading-relaxed text-ink">{events.find((event) => event.type === 'decision' && event.decision?.decision_id === block?.decision_id)?.detail ?? (block ? block.invariant ?? 'The enforcement layer refused the proposal.' : 'No block explanation is available.')}</p>
          {shadow && <div className="mt-5 border-t border-line pt-4"><p className="text-xs font-semibold text-ink">Independent grant check</p><p className="mt-1 text-xs leading-relaxed text-ink-2">The grant layer also reported “{shadow.reason}”. {shadow.shadow ? 'ArmorIQ had already stopped the request, so this check is recorded for reference only.' : 'It was a separate decision.'}</p></div>}
        </div>
      </div>
    </Panel>
      <div className="grid gap-3 sm:grid-cols-2">
      <Panel className="p-4"><p className="font-mono text-[10px] uppercase tracking-wider text-ink-3">Handler entries</p><p className="mt-2 text-2xl font-semibold text-ink">{metric}</p><p className="mt-1 text-xs text-ink-2">Reported by this run’s metrics</p></Panel>
      <Panel className="p-4"><p className="font-mono text-[10px] uppercase tracking-wider text-ink-3">Action that followed</p><p className="mt-2 text-sm font-medium text-ink">{detail.run.replans_used > 0 ? 'The run replanned within its original grant' : 'No replan was recorded'}</p><p className="mt-1 text-xs text-ink-2">Replans used: {detail.run.replans_used} of {detail.grant.limits.max_replans} allowed.</p></Panel>
    </div>
  </div>
}

function RepairStage({ detail, events }: { detail: RunDetail; events: RunEvent[] }) {
  const manifest = getManifest(detail, events)
  const commit = eventBy(events, 'execution.committed')
  const receipt = getReceipt(detail, events)
  const changes = manifest?.changes ?? receipt?.changes.map((change) => ({ row_id: change.row_id, field: change.field, current_value: change.before, new_value: change.after })) ?? []
  return <div className="grid gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(240px,.7fr)]">
    <Panel className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-4"><div><p className="font-mono text-[10px] uppercase tracking-wider text-ink-3">Exact recorded repair</p><h3 className="mt-1 text-sm font-semibold text-ink">{manifest?.snapshot_id ?? 'Snapshot repair'}</h3></div><span className="text-xs text-ink-3">{manifest ? `${changes.length} field changes` : changes.length ? `${changes.length} receipt changes` : 'No repair manifest found'}</span></div>
      {changes.length ? <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-xs"><thead className="bg-surface-2 text-ink-3"><tr><th className="px-4 py-2.5 font-medium">Record</th><th className="px-4 py-2.5 font-medium">Field</th><th className="px-4 py-2.5 font-medium">Before</th><th className="px-4 py-2.5 font-medium">Restored value</th></tr></thead><tbody className="divide-y divide-line">{changes.map((change, index) => <tr key={`${change.row_id}-${change.field}-${index}`}><td className="px-4 py-3 font-mono text-ink">{change.row_id}</td><td className="px-4 py-3 font-mono text-ink-2">{fieldLabel(change.field)}</td><td className="max-w-36 break-all px-4 py-3 text-ink-3">{change.field === 'total_cents' && typeof change.current_value === 'number' ? formatMoney(change.current_value) : pretty(change.current_value)}</td><td className="max-w-40 break-all px-4 py-3 font-medium text-[var(--outcome-allow)]">{change.field === 'total_cents' && typeof change.new_value === 'number' ? formatMoney(change.new_value) : pretty(change.new_value)}</td></tr>)}</tbody></table></div> : <p className="p-5 text-sm text-ink-2">No manifest or receipt changes are available in this run detail.</p>}
    </Panel>
    <Panel className="p-5 sm:p-6">
      <div className="flex items-center gap-2 text-sm font-semibold text-ink"><Database className="size-4 text-[var(--layer-postgres)]" aria-hidden />Write outcome</div>
      <p className="mt-3 text-sm leading-relaxed text-ink-2">{commit?.detail ?? receipt?.result ?? detail.run.outcome_summary ?? 'No database commit result was recorded.'}</p>
      <dl className="mt-4"><ValueRow label="Manifest" value={manifest?.manifest_id ?? 'Not available'} /><ValueRow label="Receipt" value={receipt?.operation_id ?? 'Not available'} /><ValueRow label="Commit count" value={String(detail.metrics.commits)} /></dl>
    </Panel>
  </div>
}

function ProofStage({ detail, events }: { detail: RunDetail; events: RunEvent[] }) {
  const receipt = getReceipt(detail, events)
  const checks: InvariantCheck[] = receipt?.checks ?? []
  const summary = detail.run.metadata.protected_checks as Record<string, unknown> | undefined
  const preserved = checks.filter((check) => check.status === 'preserved')
  const repaired = checks.filter((check) => check.status === 'repaired')
  const violated = checks.filter((check) => check.status === 'violated')
  return <div className="space-y-5">
    <Panel className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-2 text-[var(--outcome-allow)]"><ShieldCheck className="size-5" aria-hidden /><p className="font-mono text-[10px] uppercase tracking-wider">Evidence from this run</p></div><h3 className="mt-3 text-xl font-semibold text-ink">{detail.run.status === 'succeeded' ? 'The run finished successfully' : `Run status: ${detail.run.status}`}</h3><p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-2">{detail.run.outcome_summary ?? 'This run has no outcome summary.'}</p></div><span className={`border px-2.5 py-1 text-xs ${violated.length ? 'border-[var(--outcome-block)] text-[var(--outcome-block)]' : 'border-line-strong text-ink-2'}`}>{violated.length ? `${violated.length} violated checks` : checks.length ? `${preserved.length} preserved · ${repaired.length} repaired` : 'No check results returned'}</span></div>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <div className="border-t-2 border-[var(--outcome-allow)] pt-3"><p className="font-mono text-[10px] uppercase tracking-wider text-ink-3">Preserved</p><p className="mt-1 text-lg font-semibold text-ink">{summary?.preserved !== undefined ? String(summary.preserved) : checks.length ? preserved.length : 'Not recorded'}</p><p className="text-xs text-ink-2">Deleted rows, access decisions and later edits checked in the recorded evidence.</p></div>
        <div className="border-t-2 border-[var(--layer-domain)] pt-3"><p className="font-mono text-[10px] uppercase tracking-wider text-ink-3">Repaired</p><p className="mt-1 text-lg font-semibold text-ink">{summary?.repaired !== undefined ? String(summary.repaired) : checks.length ? repaired.length : 'Not recorded'}</p><p className="text-xs text-ink-2">Checks marked repaired by this run.</p></div>
        <div className={`border-t-2 ${violated.length ? 'border-[var(--outcome-block)]' : 'border-line-strong'} pt-3`}><p className="font-mono text-[10px] uppercase tracking-wider text-ink-3">Violated</p><p className="mt-1 text-lg font-semibold text-ink">{summary?.violated !== undefined ? String(summary.violated) : checks.length ? violated.length : 'Not recorded'}</p><p className="text-xs text-ink-2">A zero is shown only when the run returned its check count.</p></div>
      </div>
    </Panel>
    {checks.length > 0 && <Panel className="divide-y divide-line">
      {checks.map((check) => <div key={check.check_id} className="flex flex-wrap items-start justify-between gap-3 p-4"><div className="flex gap-3"><span className={`mt-1 size-2 shrink-0 ${check.status === 'violated' ? 'bg-[var(--outcome-block)]' : check.status === 'pending' ? 'bg-[var(--outcome-hold)]' : 'bg-[var(--outcome-allow)]'}`} aria-hidden /><div><p className="text-sm font-medium text-ink">{check.label}</p><p className="mt-1 text-xs leading-relaxed text-ink-2">{check.detail}</p></div></div><span className="font-mono text-[10px] uppercase text-ink-3">{check.status}</span></div>)}
    </Panel>}
    {!checks.length && <Panel className="p-5 text-sm text-ink-2">This run’s receipt checks are unavailable, so the walkthrough leaves protected-state results unclaimed.</Panel>}
    <p className="text-xs leading-relaxed text-ink-3">Local run evidence and synthetic records. A locally signed receipt is not sponsor attestation or independent witness evidence.</p>
  </div>
}

function StageBody({ index, detail, events }: { index: number; detail: RunDetail; events: RunEvent[] }) {
  if (index === 0) return <IncidentStage detail={detail} />
  if (index === 1) return <ScopeStage detail={detail} />
  if (index === 2) return <AttemptStage detail={detail} events={events} />
  if (index === 3) return <div className="space-y-5"><BlockStage detail={detail} events={events} /><RecordedPolicyProof /></div>
  if (index === 4) return <RepairStage detail={detail} events={events} />
  return <div className="space-y-5"><ProofStage detail={detail} events={events} /><OfflineProof /></div>
}

export default function JudgeWalkthrough() {
  const runs = useRuns()
  const selected = useMemo(() => runs.data ? selectRun(runs.data) : undefined, [runs.data])
  const detail = useRun(selected?.run_id)
  const stream = useRunEvents(selected?.run_id)
  // No live run in this workspace yet (a fresh install): replay the recorded one from its signed export.
  const bundled = useBundledRun(!selected && !runs.loading && runs.data !== undefined)
  const bundle = selected ? undefined : bundled.data
  const data = bundle?.detail ?? detail.data
  const [step, setStep] = useState(0)
  const run = data?.run ?? selected
  const heading = STEPS[step]
  const hasAttempt = data?.proposals.some((bundle) => bundle.proposal.tool === 'restore_access_grant') ?? false
  const hasBlock = data?.proposals.some((bundle) => bundle.proposal.tool === 'restore_access_grant' && bundle.decisions.some((decision) => decision.decisive && decision.outcome === 'block')) ?? false

  if (runs.loading) return <div className="space-y-5" role="status" aria-label="Finding a recorded run"><Skeleton className="h-9 w-2/3" /><Skeleton className="h-24 w-full" /><Skeleton className="h-64 w-full" /></div>
  if (runs.error && !runs.data) return <ErrorState title="Could not load recorded runs" error={runs.error} onRetry={() => void runs.refetch()} />
  if (!selected && !bundle && !bundled.failed) return <div className="space-y-5" role="status" aria-label="Loading the recorded run"><Skeleton className="h-9 w-2/3" /><Skeleton className="h-24 w-full" /><Skeleton className="h-64 w-full" /></div>
  if (!selected && !bundle) return <Panel className="p-6 sm:p-8"><div className="flex gap-3"><CircleHelp className="mt-1 size-5 shrink-0 text-ink-3" aria-hidden /><div><h1 className="text-xl font-semibold text-ink">No run is available to replay</h1><p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-2">The walkthrough reads its story from runs returned by the backend. There is no matching live replay or recorded run in the current run list.</p><div className="mt-4"><WalkLink to="/workspace" primary>Open workspace</WalkLink></div></div></div></Panel>
  if (selected && detail.error && !detail.data) return <ErrorState title="The selected run could not be opened" error={detail.error} onRetry={() => void detail.refetch()} />
  if (!data || !run) return <div className="space-y-5" role="status" aria-label="Loading run evidence"><Skeleton className="h-9 w-2/3" /><Skeleton className="h-24 w-full" /><Skeleton className="h-64 w-full" /></div>

  const events = bundle ? bundle.events : stream.events
  const completedStages = Math.min(STEPS.length, Math.max(0, step + 1))
  return <div className="mx-auto max-w-[1320px] space-y-6 pb-6" aria-labelledby="walkthrough-title">
    <header className="grid gap-5 border-b border-line pb-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
      <div><h1 id="walkthrough-title" className="text-3xl font-semibold leading-tight tracking-[-.035em] text-ink sm:text-4xl">Follow one request, from incident to proof</h1><p className="mt-3 max-w-3xl text-sm leading-relaxed text-ink-2">{hasAttempt && hasBlock ? 'See the task boundary, the agent’s out-of-scope attempt, the layer that stopped it, and the repair evidence returned by this run.' : 'Follow this run’s returned scope, decisions, repair, and proof. Each result comes from the selected run record.'}</p><div className="mt-4"><SourceTag run={run} /></div>{bundle && <p className="mt-3 max-w-3xl text-xs leading-relaxed text-ink-3">Recorded on {recordedDay(run.created_at)} with a live model and live ArmorIQ. This workspace has no live run of its own yet, so the walkthrough replays the signed export shipped with the app. Check it with <code className="font-mono">scripts/veeriq-verify</code>.</p>}<details className="mt-3 text-xs text-ink-3"><summary className="w-fit cursor-pointer underline decoration-line-strong underline-offset-4">View run details</summary><dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-[100px_1fr]"><dt>Scenario</dt><dd>{run.scenario_id}</dd><dt>Run ID</dt><dd className="break-all font-mono">{run.run_id}</dd><dt>Planner</dt><dd>{run.metadata.planner_label ?? run.planner}</dd><dt>Enforcement</dt><dd>{run.enforcement_mode}{run.plan?.simulated ? ' · simulated' : ''}</dd></dl></details></div>
      <div className="flex flex-wrap gap-2">{bundle ? <><a href={BUNDLED_EXPORT} download className={walkLinkClass(false)}>Download signed export</a><WalkLink to="/">Run it yourself</WalkLink></> : <><WalkLink to={`/runs/${run.run_id}`}>Open run workspace</WalkLink><WalkLink to="/workspace">Live workspace</WalkLink></>}</div>
    </header>

    <section className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)]" aria-label="Guided run replay">
      <nav aria-label="Walkthrough stages" className="border border-line bg-surface">
        <div className="border-b border-line px-4 py-3"><p className="text-sm font-medium text-ink">Follow the evidence</p><div className="mt-2 h-1 bg-surface-2" role="progressbar" aria-label="Walkthrough progress" aria-valuemin={1} aria-valuemax={STEPS.length} aria-valuenow={completedStages}><div className="h-full bg-[var(--primary)] transition-[width]" style={{ width: `${completedStages / STEPS.length * 100}%` }} /></div></div>
        <ol className="grid grid-cols-6 divide-x divide-line xl:block xl:divide-x-0 xl:divide-y">
          {STEPS.map((item, index) => { const Icon = item.icon; const current = index === step; return <li key={item.name}><button type="button" onClick={() => setStep(index)} aria-current={current ? 'step' : undefined} className={`flex min-h-16 w-full flex-col items-center justify-center gap-1 px-1 py-2 text-center transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--focus)] xl:min-h-0 xl:flex-row xl:justify-start xl:gap-3 xl:px-4 xl:py-3 ${current ? 'bg-surface-2 text-ink' : 'text-ink-3 hover:bg-surface-2 hover:text-ink'}`}><span className={`grid size-6 shrink-0 place-items-center border ${current ? 'border-[var(--primary)] text-[var(--primary)]' : 'border-line-strong'}`}><Icon className="size-3.5" aria-hidden /></span><span className="text-[10px] font-medium leading-tight sm:text-xs xl:text-sm">{item.name}</span></button></li> })}
        </ol>
        <div className="hidden border-t border-line p-4 xl:block"><p className="text-xs leading-relaxed text-ink-3">One recorded run, six questions. Use the step controls to move through the evidence.</p></div>
      </nav>

      <div className="min-w-0 border border-line bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-4 sm:px-6"><div><p className="font-mono text-[10px] uppercase tracking-wider text-ink-3">Step {step + 1} of {STEPS.length}</p><p className="mt-1 text-sm font-semibold text-ink">{heading.short}</p></div><p className="text-xs text-ink-3">{run.status}</p></div>
        <div className="space-y-5 p-4 sm:p-6 lg:p-7">
          <StageHeading title={['What incident was under recovery?', 'What was the operator authorizing?', 'What did the agent try?', hasBlock ? 'Which boundary stopped it?' : 'What boundary decision was recorded?', 'What repair was applied?', 'What evidence came back?'][step]}>
            {[
              'Start with the incident and task the operator asked the agent to handle.',
              'The grant defines which records, fields, and effects the run is authorized to touch.',
              'The replay exposes the recorded untrusted instruction and the action the agent proposed after reading it.',
              'Follow the proposal to the actual decisive decision and see whether its tool handler ran.',
              'Inspect the change set that the run prepared and the database commit result it recorded.',
              'Finish with this run’s own receipt checks, including what stayed protected and what changed.',
            ][step]}
          </StageHeading>
          <StageBody index={step} detail={data} events={events} />
        </div>
        <footer className="flex items-center justify-between gap-3 border-t border-line px-4 py-3 sm:px-6"><Button variant="secondary" size="sm" disabled={step === 0} icon={<ArrowLeft className="size-3.5" />} onClick={() => setStep((current) => Math.max(0, current - 1))}>Back</Button><span className="text-xs text-ink-3" aria-live="polite">{heading.name} · {step + 1} / {STEPS.length}{stream.connection === 'live' ? ' · event feed connected' : ''}</span>{step < STEPS.length - 1 ? <Button variant="primary" size="sm" iconRight={<ArrowRight className="size-3.5" />} onClick={() => setStep((current) => Math.min(STEPS.length - 1, current + 1))}>Next</Button> : bundle ? <WalkLink to="/" primary>Run it yourself <ArrowRight className="size-3.5" aria-hidden /></WalkLink> : <WalkLink to={`/runs/${run.run_id}`} primary>Open full run <ArrowRight className="size-3.5" aria-hidden /></WalkLink>}</footer>
      </div>
    </section>
  </div>
}
