import { WhyRecovery } from '@/components/domain/WhyRecovery'
import { useCallback, useEffect, useRef, useState } from 'react'
import { clearQueryCache } from '@/api/cache'
import { Link } from 'react-router-dom'
import { useMotionOK } from '@/lib/motion'
import { ArrowRight, RotateCcw, Zap } from 'lucide-react'
import { api, errorMessage } from '@/api/client'
import { invalidate, invalidateAppData, TAGS } from '@/api/bus'
import { useAppState, useProtectedChecks, useRuns, useScenarios, useSnapshotDiff, useSystemStatus } from '@/api/hooks'
import { useSession } from '@/api/session'
import type { GrantDraft, ScenarioSpec } from '@/api/types'
import { GrantReview } from '@/components/domain'
import { Button, ErrorState, Modal, RunStatusPill, Skeleton, TimeAgo, useToast } from '@/components/ui'
import { resetDemo } from '@/components/shell/ResetDemo'
import { Technical } from '@/lib/detail'
import { plainOutcome } from './outcome'
import { GuidedTour } from './GuidedTour'
import { IncidentOverview } from './IncidentOverview'
import { RecentRuns } from './RecentRuns'
import { ScenarioLauncher } from './ScenarioLauncher'

export default function MissionControl() {
  const { identity } = useSession()
  const toast = useToast()
  const reduce = !useMotionOK()
  const status = useSystemStatus()
  const appState = useAppState()
  const diff = useSnapshotDiff()
  const checks = useProtectedChecks()
  const scenarios = useScenarios()
  const runs = useRuns()

  const [launchingId, setLaunchingId] = useState<string | null>(null)
  const [draft, setDraft] = useState<{ grant: GrantDraft; scenario: ScenarioSpec } | null>(null)
  const [dirtyOffer, setDirtyOffer] = useState<{ grant: GrantDraft; scenario: ScenarioSpec } | null>(null)
  const [resetting, setResetting] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const scenariosRef = useRef<HTMLElement>(null)

  // Coming back to this tab: data may have changed under us (a run committed, a reset happened).
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState !== 'visible') return
      invalidateAppData()
      invalidate(TAGS.runs, TAGS.status)
    }
    document.addEventListener('visibilitychange', refresh)
    window.addEventListener('focus', refresh)
    return () => {
      document.removeEventListener('visibilitychange', refresh)
      window.removeEventListener('focus', refresh)
    }
  }, [])

  const launch = useCallback(
    async (scenario: ScenarioSpec, autoReset = false) => {
      setLaunchingId(scenario.scenario_id)
      try {
        const grant = await api.post<GrantDraft>('/grants/draft', {
          scenario_id: scenario.scenario_id,
          ...(autoReset ? { auto_reset: true } : {}),
        })
        if (autoReset) {
          clearQueryCache()
          invalidate(TAGS.appState, TAGS.checks, TAGS.diff, TAGS.runs, TAGS.approvals, TAGS.metrics, TAGS.status)
        }
        // The demo data was already repaired in this generation: offer a fresh start instead of a confusing second run.
        if (!autoReset && grant.fixture?.dirty) {
          setDirtyOffer({ grant, scenario })
        } else {
          setDraft({ grant, scenario })
          setReviewOpen(true)
        }
      } catch (err) {
        toast.error('Could not draft the grant', errorMessage(err))
      } finally {
        setLaunchingId(null)
      }
    },
    [toast],
  )

  const resetAndRun = async (scenario: ScenarioSpec) => {
    setResetting(true)
    try {
      await resetDemo()
      setDirtyOffer(null)
      await launch(scenario)
    } catch (err) {
      toast.error('Reset failed', errorMessage(err))
    } finally {
      setResetting(false)
    }
  }

  const flagship = scenarios.data?.find((s) => s.kind === 'flagship')
  const isOperator = identity?.role === 'operator' && identity.tenant_id === 'atlas'
  const damagedCount = diff.data?.filter((r) => r.condition === 'damaged').length
  const latest = runs.data ? [...runs.data].sort((a, b) => b.created_at.localeCompare(a.created_at))[0] : undefined
  // Nothing left to repair and a run already exists: the payoff is the last run, not another launch button.
  const repaired = !!latest && (appState.data?.fixture?.dirty === true || damagedCount === 0)
  const scrollToScenarios = () => scenariosRef.current?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
  if (!identity) return null
  const tour = <GuidedTour scenarios={scenarios.data} runs={runs.data} launchingId={launchingId} onLaunch={(s) => void launch(s)} error={scenarios.error || runs.error} onRetry={() => void Promise.all([scenarios.refetch(), runs.refetch()])} />

  return (
    <div className="space-y-7">
      {/* Viewing as another tenant: explain that first. */}
      {identity.tenant_id !== 'atlas' && tour}

      <section className="recovery-intro grid items-start gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" aria-labelledby="hero-title">
        <div className="py-1">
          <h1 id="hero-title" className="recovery-headline">
            Repair the damage.<br /><span>Keep the decisions.</span>
          </h1>
          <p className="mt-4 max-w-lg text-[15px] leading-relaxed text-ink-2">Restore approved values from the past. Keep today’s deletions, revoked access, and later updates intact. You decide exactly what may change. The agent repairs within that permission.</p>
          <div className="mt-5 flex flex-wrap items-center gap-2">
            {isOperator && repaired ? <>
              <Link to="/walkthrough"><Button variant="primary" size="lg" iconRight={<ArrowRight className="size-4" />}>See the poisoned request stopped</Button></Link>
              <Button variant="secondary" size="lg" icon={<RotateCcw className="size-4" />} loading={launchingId === flagship?.scenario_id} disabled={!flagship || launchingId !== null} onClick={() => flagship && void launch(flagship)}>Run a fresh recovery</Button>
            </> : isOperator ? <Button variant="primary" size="lg" icon={<Zap className="size-4" />} loading={launchingId === flagship?.scenario_id} disabled={!flagship || launchingId !== null} onClick={() => flagship && void launch(flagship)}>Review recovery scope</Button> : identity.tenant_id !== 'atlas' ? <Button variant="secondary" onClick={scrollToScenarios}>Explore the scenarios</Button> : <Link to="/approvals"><Button variant="primary" size="lg" iconRight={<ArrowRight className="size-4" />}>Open approvals</Button></Link>}
            {!(isOperator && repaired) && <Link to="/walkthrough" className="inline-flex min-h-11 items-center gap-2 px-3 text-sm font-medium text-ink hover:underline underline-offset-4">See the poisoned request stopped <ArrowRight className="size-4" aria-hidden /></Link>}
          </div>
          {runs.error && !runs.data ? <ErrorState compact error={runs.error} title="Last run did not load" onRetry={() => void runs.refetch()} /> : !runs.data ? <div className="mt-5 space-y-2" role="status" aria-label="Loading last run"><Skeleton className="h-4 w-1/2" /><Skeleton className="h-8 w-full" /></div> : latest ? <div className="mt-5 border-t border-line pt-4">
            <div className="flex flex-wrap items-center gap-2 text-xs text-ink-3"><span>Last run</span><RunStatusPill status={latest.status} /><TimeAgo value={latest.created_at} /></div>
            <p className="mt-2 text-sm leading-relaxed text-ink-2">{plainOutcome(latest)}</p>
            {latest.outcome_summary && <Technical><p className="mt-2 text-xs leading-relaxed text-ink-3">{latest.outcome_summary}</p></Technical>}
            <Link to={`/runs/${latest.run_id}`} className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-ink hover:underline underline-offset-4">Open run <ArrowRight className="size-3.5" aria-hidden /></Link>
          </div> : <p className="mt-4 text-sm text-ink-3">Synthetic incident · Review the exact scope before the agent starts.</p>}
        </div>
        <IncidentOverview state={appState} diff={diff} checks={checks} />
      </section>
      {identity.tenant_id === 'atlas' && <details className="guided-exploration"><summary>Explore approvals, tenant isolation, and the proof</summary><div className="pt-5">{tour}</div></details>}

      <section ref={scenariosRef} aria-labelledby="scenarios-title" className="scroll-mt-28">
        <div className="mb-4 max-w-2xl">
          <h2 id="scenarios-title" className="text-xl font-semibold tracking-[-0.025em] text-ink">
            Choose a scenario
          </h2>
          <p className="mt-1.5 text-[14px] leading-relaxed text-ink-2">
            {repaired ? "This prepared incident has already been repaired. Open the recorded walkthrough to see the poisoned request stopped. An incident operator can review a rerun and choose whether to reset the synthetic data." : "An incident operator reviews and authorizes the exact scope before a run starts. Approvers review high-value repairs from the Approvals page."}
          </p>
        </div>
        <ScenarioLauncher
          scenarios={scenarios.data}
          error={scenarios.error}
          onRetry={() => void scenarios.refetch()}
          identity={identity}
          launchingId={launchingId}
          repaired={repaired}
          onLaunch={(s) => void launch(s)}
        />
      </section>

      {identity.tenant_id === 'atlas' && <WhyRecovery />}

      <RecentRuns
        runs={runs.data}
        error={runs.error}
        onRetry={() => void runs.refetch()}
        scenarios={scenarios.data}
        onStart={scrollToScenarios}
        canStart={isOperator}
      />

      <Modal
        open={!!dirtyOffer}
        onClose={() => setDirtyOffer(null)}
        dismissable={!resetting}
        width="480px"
        title="The demo data is already repaired"
        description={dirtyOffer?.grant.fixture?.note ?? 'A previous run restored the damaged orders, so this scenario would have little to repair.'}
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="ghost"
              disabled={resetting}
              onClick={() => {
                if (dirtyOffer) {
                  setDraft(dirtyOffer)
                  setReviewOpen(true)
                }
                setDirtyOffer(null)
              }}
            >
              Review current-data grant
            </Button>
            <Button variant="primary" loading={resetting} onClick={() => dirtyOffer && void resetAndRun(dirtyOffer.scenario)} data-autofocus>
              Reset and review grant
            </Button>
          </div>
        }
      >
        <p className="text-[13px] leading-snug text-ink-2">
          Resetting puts the orders back to their damaged state and cancels anything still running. Finished runs stay in the history.
        </p>
      </Modal>

      <GrantReview
        open={reviewOpen}
        onClose={() => setReviewOpen(false)}
        grant={draft?.grant ?? null}
        scenario={draft?.scenario}
        status={status.data}
      />
    </div>
  )
}
