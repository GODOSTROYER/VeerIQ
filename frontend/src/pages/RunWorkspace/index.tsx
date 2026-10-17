import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Compass, History, RefreshCw, WifiOff } from 'lucide-react'
import { api, API_BASE, ApiError, errorMessage } from '@/api/client'
import { invalidate, TAGS, useAppState, useProtectedChecks, useRun, useRunEvents, useScenarios, useSession, useSnapshotDiff } from '@/api/hooks'
import { TERMINAL_RUN_STATUSES, type ActionProposal, type Run, type RunEvent, type RunStatus } from '@/api/types'
import { tint } from '@/lib/color'
import { isSimulatedEnforcement, type EnforcementFacts } from '@/lib/layers'
import { Badge, Button, Disclosure, EmptyState, ErrorState, NumberRoll, Panel, RunStatusPill, Skeleton, SkeletonLines, StatusPill, useToast } from '@/components/ui'
import { useMinWidth, useReplay } from './hooks'
import { actionSentence, argOrderIds, buildRunView, parseAnnotations, rec, runHeading, type ActionCtx, type ProposalItem, type RunView } from './model'
import { buildProof, decisionChecks, isHeld, recordedProtectedChecks, targetOrders } from './proof'
import { CancelDialog, plannerBadgeText, ReplayBar, RunHeader } from './Header'
import { ScopeColumn } from './ScopeColumn'
import { Timeline } from './Timeline'
import { type CardCtx } from './TimelineCards'
import { Scoreboard } from './Scoreboard'
import { AuthorityBoundary } from './AuthorityBoundary'
import { BoundaryStory } from './BoundaryStory'
import { EffectsColumn } from './EffectsColumn'
import { EvidenceDrawer } from './EvidenceDrawer'
import { GateStage } from './GateStage'
import { PhaseRail } from './PhaseRail'
import { Certificate } from './Certificate'

const COLUMNS = 'grid items-start gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,1fr)]'
const STICKY = 'space-y-5 xl:sticky xl:top-[88px]'

function WorkspaceSkeleton() {
  return <div className="space-y-5" role="status" aria-label="Loading run">
    <Skeleton className="h-8 w-80 max-w-full" /><Skeleton className="h-9 w-full rounded-xl" />
    <div className="rounded-2xl border border-line bg-raised p-6"><Skeleton className="h-6 w-2/3" /><div className="mt-6 grid grid-cols-6 gap-3">{Array.from({ length: 6 }, (_, i) => <div key={i}><Skeleton className="mx-auto size-12 rounded-xl" /><Skeleton className="mt-3 h-3 w-full" /></div>)}</div><Skeleton className="mt-6 h-5 w-3/4" /></div>
    <Skeleton className="h-6 w-full" /><div className={COLUMNS}><div className="space-y-3">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-12 w-full rounded-lg" />)}</div><div className="space-y-4"><Skeleton className="h-48 rounded-2xl" /><Skeleton className="h-32 rounded-2xl" /></div></div>
  </div>
}

function Banner({ icon, children, tone = 'var(--outcome-hold)' }: { icon: ReactNode; children: ReactNode; tone?: string }) {
  return (
    <div
      role="status"
      className="mb-4 flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-[13px] leading-snug text-ink-2"
      style={{ borderColor: tint(tone, 45), background: tint(tone, 8) }}
    >
      <span className="mt-0.5 shrink-0" style={{ color: tone }}>
        {icon}
      </span>
      <span>{children}</span>
    </div>
  )
}

/** A synthetic run.finished entry, used only when the run is over but its event never reached this page. */
function syntheticFinish(run: Run, metrics: unknown): RunEvent {
  return {
    seq: Number.MAX_SAFE_INTEGER,
    run_id: run.run_id,
    ts: run.finished_at ?? run.updated_at,
    type: 'run.finished',
    actor: 'system',
    title: 'Run finished',
    detail: run.outcome_summary ?? '',
    proposal_id: null,
    decision: null,
    data: { status: run.status, outcome_summary: run.outcome_summary, metrics },
  }
}

function latestDecisive(proposals: ProposalItem[]): ProposalItem | undefined { return proposals[proposals.length - 1] }

export default function RunWorkspace() {
  const { runId } = useParams<{ runId: string }>()
  const { authMode, identity, identities, signIn } = useSession()
  const navigate = useNavigate()
  const compact = !useMinWidth(640)
  const toast = useToast()

  const runQ = useRun(runId)
  const notFound = runQ.error instanceof ApiError && (runQ.error.status === 404 || runQ.error.status === 403)
  const stream = useRunEvents(notFound ? undefined : runId)
  const scenarios = useScenarios()
  const appState = useAppState(!notFound)
  const checks = useProtectedChecks(!notFound)
  const diff = useSnapshotDiff(!notFound)

  const detail = runQ.data
  const run = detail?.run
  const terminal = run ? TERMINAL_RUN_STATUSES.includes(run.status) : false
  const live = !!run && !terminal
  const generationMismatch = !!appState.data && !!run && appState.data.fixture_generation !== run.fixture_generation

  /* Replay: a prefix of the recorded events, rendered by the same code as a live run. */
  const replay = useReplay(stream.events)
  const visible = useMemo(() => (replay.active ? stream.events.slice(0, replay.cursor) : stream.events), [replay.active, replay.cursor, stream.events])
  const detailProposals = useMemo(() => {
    const m = new Map<string, ActionProposal>()
    detail?.proposals.forEach((b) => m.set(b.proposal.proposal_id, b.proposal))
    return m
  }, [detail])
  /* The note the agent saw comes from the event stream. App state is the fallback, and only for scenarios that inject one. */
  const injects = scenarios.data?.find((s) => s.scenario_id === run?.scenario_id)?.inject_annotation === true
  const stateNotes = appState.data?.snapshot ? rec(appState.data.snapshot).annotations : undefined
  const buildOptions = useMemo(() => ({ fallbackAnnotations: injects ? parseAnnotations(stateNotes) : [] }), [injects, stateNotes])
  const view: RunView = useMemo(
    () => buildRunView(visible, detailProposals, !replay.active, buildOptions),
    [visible, detailProposals, replay.active, buildOptions],
  )
  const fullView: RunView = useMemo(
    () => (replay.active ? buildRunView(stream.events, detailProposals, true, buildOptions) : view),
    [replay.active, stream.events, detailProposals, view, buildOptions],
  )
  /* One set of facts for every "Live" or "Simulated" label on this page, read from the whole run, not the replay prefix. */
  const enforcement: EnforcementFacts = useMemo(
    () => ({
      enforcement_mode: run?.enforcement_mode,
      plan: run?.plan,
      decisions: [...(detail?.proposals ?? []).flatMap((b) => b.decisions), ...fullView.decisions.map((x) => x.decision)],
    }),
    [run, detail, fullView.decisions],
  )

  const items = useMemo(() => {
    if (!run || replay.active || !terminal || view.finish) return view.items
    return [...view.items, { key: 'finish-synth', seq: Number.MAX_SAFE_INTEGER, ts: run.finished_at ?? run.updated_at, kind: 'finish' as const, event: syntheticFinish(run, detail?.metrics) }]
  }, [run, replay.active, terminal, view, detail?.metrics])

  /* Selection: pinned by the viewer, otherwise the latest decisive action. */
  const [pinnedId, setPinnedId] = useState<string | null>(null)
  useEffect(() => {
    setPinnedId(null)
  }, [replay.active, runId])
  useEffect(() => {
    if (replay.active && replay.cursor === 0) setPinnedId(null)
  }, [replay.active, replay.cursor])
  const selected = useMemo(() => {
    const pinned = pinnedId ? view.proposals.find((p) => p.proposalId === pinnedId) : undefined
    return pinned ?? latestDecisive(view.proposals)
  }, [pinnedId, view.proposals])
  const pinned = !!pinnedId && selected?.proposalId === pinnedId

  const nameOf = useCallback(
    (id: string | null | undefined) => (id ? (identities.find((i) => i.identity_id === id)?.name ?? id) : 'A reviewer'),
    [identities],
  )

  const actionCtx: ActionCtx = useMemo(
    () => ({
      accessPrincipal: (grantId) => appState.data?.access_grants.find((g) => g.grant_id === grantId)?.principal,
      manifestRows: (id) => Array.from(new Set(fullView.manifests.find((m) => m.manifest_id === id)?.changes.map((c) => c.row_id) ?? [])),
    }),
    [appState.data, fullView.manifests],
  )

  const status: RunStatus | undefined = replay.active ? (view.status ?? 'created') : run?.status
  const useEventCounts = view.items.length > 0 || replay.active
  const steps = useEventCounts ? view.steps : (run?.steps_used ?? 0)
  const replans = useEventCounts ? view.replans : (run?.replans_used ?? 0)
  const commits = useEventCounts ? view.commits : (detail?.grant.commits_used ?? 0)

  const [exporting, setExporting] = useState(false)
  const exportEvidence = useCallback(async () => {
    if (!runId) return
    setExporting(true)
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/sealed-evidence`, { credentials: 'include' })
      if (!res.ok) throw new Error(`The server answered ${res.status}.`)
      const url = URL.createObjectURL(await res.blob())
      const a = document.createElement('a')
      a.href = url
      a.download = `veeriq-signed-evidence-${runId}.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 2000)
      toast.success('Signed evidence exported', 'Locally signed event chain and measured effects. No credentials or bearer tokens.')
    } catch (err) {
      toast.error('Evidence did not export', errorMessage(err))
    } finally {
      setExporting(false)
    }
  }, [runId, toast])

  /* The listed scenario title, when the scenario list has one. Import runs fall back to a human title, see runHeading. */
  const listedTitle = scenarios.data?.find((s) => s.scenario_id === run?.scenario_id)?.title

  /* Second-reviewer shortcut: only offered to the run's operator, and only for a same-tenant reviewer. */
  const reviewer = useMemo(
    () => (authMode === 'demo' && identity?.role === 'operator' ? identities.find((i) => i.role === 'reviewer' && i.tenant_id === identity.tenant_id) : undefined),
    [authMode, identity, identities],
  )
  const reviewAs = useMemo(
    () =>
      reviewer
        ? {
            name: reviewer.name,
            go: async (approvalId: string) => {
              try {
                await signIn(reviewer.identity_id)
                navigate(`/approvals?focus=${encodeURIComponent(approvalId)}`)
              } catch (err) {
                toast.error('Could not switch to the reviewer', errorMessage(err))
              }
            },
          }
        : undefined,
    [reviewer, signIn, navigate, toast],
  )

  const recordedChecks = useMemo(() => recordedProtectedChecks(view), [view])

  const cardCtx: CardCtx = useMemo(
    () => ({
      action: actionCtx,
      plan: replay.active ? view.plan : view.plan ?? run?.plan ?? undefined,
      run,
      grant: detail?.grant,
      view,
      handlerEntries: replay.active && !view.finish ? undefined : detail?.metrics.prohibited_handler_entries,
      nameOf,
      enforcement,
      selectedId: selected?.proposalId,
      onSelect: setPinnedId,
      ticking: live && !replay.active,
      checks: recordedChecks?.checks,
      checkEvidence: recordedChecks,
      scenarioTitle: run ? runHeading(run, listedTitle).title : undefined,
      onExport: () => void exportEvidence(),
      exporting,
      reviewAs,
    }),
    [actionCtx, view, run, detail?.grant, detail?.metrics.prohibited_handler_entries, nameOf, enforcement, selected?.proposalId, live, replay.active, recordedChecks, listedTitle, exportEvidence, exporting, reviewAs],
  )

  const plan = cardCtx.plan
  const offPlanTools = useMemo(() => {
    if (!plan || plan.steps.length === 0) return []
    return Array.from(new Set(view.proposals.filter((p) => !plan.steps.includes(p.tool)).map((p) => p.tool)))
  }, [plan, view.proposals])
  const beaconAttempts = useMemo(
    () =>
      view.proposals.filter(
        (p) => p.status === 'blocked' && (p.args.tenant_id === 'beacon' || argOrderIds(p.args).some((id) => id.startsWith('B-'))),
      ).length,
    [view.proposals],
  )

  /* Evidence. */
  const decisionRows = useMemo(() => {
    if (fullView.decisions.length > 0) return fullView.decisions
    return (detail?.proposals ?? []).flatMap((b) => b.decisions.map((d) => ({ decision: d, tool: b.proposal.tool })))
  }, [fullView.decisions, detail?.proposals])
  const manifestRows = fullView.manifests.length > 0 ? fullView.manifests : (detail?.proposals.flatMap((b) => (b.manifest ? [b.manifest] : [])) ?? [])
  const receiptRows = fullView.receipts.length > 0 ? fullView.receipts : (detail?.receipts ?? [])
  const proof = useMemo(
    () =>
      buildProof({
        view: fullView,
        run,
        grant: detail?.grant,
        checks: checks.data,
        metrics: detail?.metrics,
        live,
        generationMismatch,
        nameOf,
        enforcement,
      }),
    [fullView, run, detail?.grant, detail?.metrics, checks.data, live, nameOf, generationMismatch, enforcement],
  )
  const [evidenceOpen, setEvidenceOpen] = useState(false)

  const [cancelOpen, setCancelOpen] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const cancelRun = useCallback(async () => {
    if (!runId) return
    setCancelling(true)
    try {
      await api.post<Run>(`/runs/${runId}/cancel`)
      invalidate(TAGS.run(runId), TAGS.runs, TAGS.approvals)
      toast.success('Run cancelled')
      setCancelOpen(false)
    } catch (err) {
      toast.error('The run could not be cancelled', errorMessage(err))
    } finally {
      setCancelling(false)
    }
  }, [runId, toast])


  /* Page states. */
  if (!runId || notFound) {
    return (
      <EmptyState
        icon={<Compass className="size-5" />}
        title="This run was not found"
        description="The link may be old, or the run was removed when the demo was reset. Runs from other tenants are not visible here."
        action={
          <Link to="/workspace">
            <Button variant="secondary">Back to Workspace</Button>
          </Link>
        }
      />
    )
  }
  if (runQ.error && !detail) return <ErrorState error={runQ.error} title="This run did not load" onRetry={() => void runQ.refetch()} />
  if (!detail || !run) return <WorkspaceSkeleton />

  const heading = runHeading(run, listedTitle)
  const simulated = isSimulatedEnforcement(enforcement)
  const starter = identities.find((i) => i.identity_id === run.created_by)?.name ?? run.created_by
  const effectiveStatus = status ?? run.status
  const stageFinished = !!view.finish || TERMINAL_RUN_STATUSES.includes(effectiveStatus)
  const applying = effectiveStatus === 'executing' && view.proposals.at(-1)?.tool === 'apply_repair_manifest' && view.proposals.at(-1)?.status === 'pending'
  const reconnecting = live && (stream.connection === 'reconnecting' || stream.connection === 'polling')
  const selectedAction = selected ? actionSentence(selected.tool, selected.args, actionCtx) : undefined
  const targetIds = selected ? argOrderIds(selected.args, actionCtx) : []
  const header = <RunHeader
        run={run}
        title={heading.title}
        rawId={heading.rawId}
        enforcement={enforcement}
        status={effectiveStatus}
        plan={plan}
        steps={steps}
        maxSteps={detail.grant.limits.max_steps}
        replans={replans}
        maxReplans={detail.grant.limits.max_replans}
        live={live}
        replay={replay}
        canReplay={terminal && stream.events.length > 0}
        canCancel={identity?.role === 'operator' && live && !replay.active}
        starterName={starter}
        onCancel={() => setCancelOpen(true)}
        onOpenEvidence={() => setEvidenceOpen(true)}
        onExport={() => void exportEvidence()}
        exporting={exporting}
        applying={applying}
      />
  const promises = <Scoreboard workflow={run.workflow} view={view} enforcement={enforcement} grant={detail.grant} checks={checks.data} appState={appState.data} metrics={detail.metrics} live={live && !replay.active} replaying={replay.active} generationMismatch={generationMismatch} />
  const guarded = decisionChecks(cardCtx.checks)
  const beacon = cardCtx.checks?.find(check => check.category === 'tenant_isolation')
  const repaired = view.committedOrderIds.filter(id => targetOrders(detail.grant).includes(id)).length
  return (
    <div className={compact ? 'space-y-3' : 'space-y-5'} style={{ overflowAnchor: 'none' }}>
      {compact ? <header className="space-y-2">
        <h1 className="text-lg font-semibold leading-snug tracking-tight">{heading.title}</h1>
        {heading.rawId && <p className="break-all font-mono text-xs text-ink-3">{heading.rawId}</p>}
        <div className="flex flex-wrap items-center gap-1.5">{applying ? <StatusPill tone="info" live={!replay.active}>Applying repair</StatusPill> : <RunStatusPill status={effectiveStatus} />}<Badge size="sm">{run.planner_kind === 'harness' ? 'Boundary test · fixed probes' : run.planner_kind === 'scripted' ? 'Scripted recovery' : 'Live model'}</Badge><Badge size="sm" color="var(--layer-armoriq)" dashed={simulated}>{simulated ? 'Simulated ArmorIQ' : 'Live ArmorIQ'}</Badge></div>
        <div className="flex flex-wrap gap-1.5">
          {terminal && !replay.active && stream.events.length > 0 && <Button size="sm" variant="secondary" onClick={replay.start}>Replay</Button>}
          {replay.active && <><Button size="sm" variant="secondary" onClick={replay.toggle}>{replay.playing ? 'Pause' : replay.cursor >= replay.total ? 'Replay again' : 'Resume'}</Button><Button size="sm" variant="ghost" disabled={replay.cursor >= replay.total} onClick={replay.skipToEnd}>Skip to end</Button><Button size="sm" variant="outline" onClick={replay.stop}>Exit replay</Button></>}
          {!replay.active && <><Button size="sm" variant="outline" onClick={() => setEvidenceOpen(true)}>Evidence</Button>
          <Button size="sm" variant="outline" loading={exporting} onClick={() => void exportEvidence()}>Export</Button></>}
          {identity?.role === 'operator' && live && !replay.active && <Button size="sm" variant="ghost" onClick={() => setCancelOpen(true)}>Cancel run</Button>}
        </div>
        <Disclosure className="border-0 bg-transparent [&>button]:px-0 [&>button]:py-1" summary={<span className="text-xs font-normal">Run details · {plannerBadgeText(run)}</span>}>{header}{replay.active && <ReplayBar run={run} replay={replay} />}</Disclosure>
      </header> : header}

      {compact ? <Disclosure className="[&>button]:h-14 [&>button]:px-3 [&>button]:py-2.5" summary={<span className="flex flex-wrap gap-x-3 gap-y-1 text-xs font-normal"><span>Repaired <span className="tabular text-allow"><NumberRoll value={repaired} />/{targetOrders(detail.grant).length}</span></span><span>Kept <span className="tabular">{guarded.length ? `${guarded.filter(isHeld).length}/${guarded.length}` : 'checking'}</span></span><span>Stopped <span className="tabular text-block"><NumberRoll value={view.blockedProposals} /></span></span><span>Beacon {beacon ? isHeld(beacon) ? 'untouched' : 'changed' : 'checking'}</span></span>}>{promises}</Disclosure> : promises}

      {replay.active && !compact && <ReplayBar run={run} replay={replay} />}

      <BoundaryStory view={view} onInspect={setPinnedId} />
      <AuthorityBoundary proposal={selected} metrics={detail.metrics} replaying={replay.active} />
      <GateStage selected={selected} pinned={pinned} onLive={() => setPinnedId(null)} ctx={cardCtx} replay={replay.active} finished={stageFinished} />
      <PhaseRail view={view} status={effectiveStatus} finished={stageFinished} />

      <div className={COLUMNS}>
        <section aria-label="Agent and decisions" className="order-1 min-w-0 xl:order-none">
          <Panel
            title={replay.active ? 'Replay of the agent’s run' : 'What the agent did'}
            subtitle={live ? 'Live. New steps appear as they happen.' : 'Every action, and what each layer decided.'}
            icon={<History className="size-4" />}
          >
            {reconnecting && (
              <Banner icon={stream.connection === 'polling' ? <RefreshCw className="size-4" /> : <WifiOff className="size-4" />}>
                {stream.connection === 'polling'
                  ? 'The live connection is down. Checking for new steps every couple of seconds instead.'
                  : 'Live connection lost. Reconnecting, and nothing will be missed.'}
              </Banner>
            )}
            {generationMismatch && terminal && !replay.active && (
              <Banner icon={<History className="size-4" />}>This run was recorded before the demo data was last reset. Its timeline and evidence are unchanged.</Banner>
            )}
            {items.length === 0 ? (
              live || replay.active || stream.connection === 'connecting' ? (
                <div className="py-2"><p className="mb-3 text-[13px] text-ink-3">Waiting for the agent’s first step</p><SkeletonLines lines={3} /></div>
              ) : (
                <EmptyState compact title="No events were recorded for this run" description="The run exists but its event log is empty. The evidence export still has its grant and plan." />
              )
            ) : (
              <Timeline items={items.filter(item => item.kind !== 'finish')} ctx={cardCtx} active={live || replay.active} />
            )}
          </Panel>
        </section>

        <aside aria-label="Application effects" className={`${STICKY} order-2 xl:order-none`}>
          <EffectsColumn
            selected={selected}
            pinned={pinned}
            onFollowLatest={() => setPinnedId(null)}
            actionText={selectedAction}
            diffRows={diff.data}
            diffError={diff.error}
            onRetryDiff={() => void diff.refetch()}
            allReceipts={fullView.receipts}
            repairedIds={view.committedOrderIds}
            targetIds={targetIds}
            targetRecordIds={targetOrders(detail.grant)}
            checks={checks.data}
            recordedChecks={recordedChecks?.checks}
            checksAreRecorded={recordedChecks !== undefined}
            checksError={checks.error}
            appState={appState.data}
            beaconAttempts={beaconAttempts}
            generationMismatch={generationMismatch}
            replaying={replay.active}
            live={live && !replay.active}
            workflow={run.workflow}
            visibleReceipts={view.receipts}
          />
          <ScopeColumn grant={detail.grant} plan={plan} steps={steps} replans={replans} commits={commits} offPlanTools={offPlanTools} loading={false} />
        </aside>
      </div>

      {items.find(item => item.kind === 'finish') && <Certificate event={(items.find(item => item.kind === 'finish') as Extract<typeof items[number], { kind: 'finish' }>).event} ctx={cardCtx} />}

      <EvidenceDrawer
        open={evidenceOpen}
        onClose={() => setEvidenceOpen(false)}
        runId={run.run_id}
        proof={proof}
        decisions={decisionRows}
        manifests={manifestRows}
        receipts={receiptRows}
        events={stream.events}
        enforcement={enforcement}
        onExport={() => void exportEvidence()}
        exporting={exporting}
      />
      <CancelDialog open={cancelOpen} onClose={() => setCancelOpen(false)} onConfirm={() => void cancelRun()} busy={cancelling} />
    </div>
  )
}
