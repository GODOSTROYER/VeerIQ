import { ReliabilityProof } from '@/components/domain/ReliabilityProof'
import { OfflineProof } from '@/components/domain/OfflineProof'
import { RecordedPolicyProof } from '@/components/domain/RecordedPolicyProof'
import { useEffect, useMemo } from 'react'
import { Play, ShieldCheck } from 'lucide-react'
import { errorMessage } from '@/api/client'
import { useMetrics, useSystemStatus, useVerification } from '@/api/hooks'
import { useSession } from '@/api/session'
import type { Layer } from '@/api/types'
import { Badge, Button, Disclosure, EmptyState, ErrorState, Panel, Skeleton, useToast } from '@/components/ui'
import { Technical } from '@/lib/detail'
import { formatDuration, relativeTime } from '@/lib/format'
import { BoundaryHeld } from './BoundaryHeld'
import { GuaranteeMatrix, isLayer } from './GuaranteeMatrix'
import { LayerBar } from './LayerBar'
import { LiveEvidence } from './LiveEvidence'
import { MetricTiles } from './MetricTiles'
import { SummaryBand } from './SummaryBand'

export default function ProofBoard() {
  const { identity, authMode } = useSession()
  const toast = useToast()
  const status = useSystemStatus()
  const metrics = useMetrics()
  const verification = useVerification()
  const { run, running, starting, refetch } = verification
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => void refetch(), 1500)
    return () => window.clearInterval(timer)
  }, [running, refetch])
  const isOperator = identity?.role === 'operator' && authMode === 'demo'
  // The hook briefly retains the previous suite until the new run's first GET arrives.
  // Do not describe its completed rows as progress in the new suite.
  const currentRun = running && run?.status !== 'running' ? null : run
  const results = useMemo(() => currentRun?.results ?? [], [currentRun])
  const layerCounts = useMemo(() => {
    const counts = (metrics.data?.blocked_by_layer ?? {}) as Partial<Record<Layer, number>>
    if (Object.values(counts).some(n => (n ?? 0) > 0)) return { counts, source: 'Counted across every run: each stopped action is attributed to the deciding layer.' }
    const fallback: Partial<Record<Layer, number>> = {}
    for (const r of results) if (isLayer(r.layer_actual)) fallback[r.layer_actual] = (fallback[r.layer_actual] ?? 0) + 1
    return { counts: fallback, source: 'Counted from verification checks: each check is attributed to the layer that actually acted.' }
  }, [metrics.data, results])
  const startError = verification.error
  useEffect(() => { if (startError) toast.error('Verification suite problem', errorMessage(startError)) }, [startError, toast])
  const action = <div className="space-y-2">
    <Button variant={isOperator ? 'primary' : 'secondary'} icon={<Play className="size-4" />} disabled={!isOperator} loading={starting || running} onClick={() => void verification.start()}>{running ? 'Suite is running' : starting ? 'Starting suite' : results.length ? 'Run it again' : 'Run verification suite'}</Button>
    <p className="max-w-56 text-xs text-ink-3">{isOperator ? 'Resets shared demo data; takes several minutes.' : authMode === 'oidc' ? 'Demo fixture resets are disabled for organization sign-in.' : 'Only an operator can start the suite.'}</p>
  </div>
  return <div className="space-y-7">
    <header><h1 className="text-3xl font-semibold tracking-[-0.03em] text-ink">Proof board</h1><p className="mt-2 max-w-[72ch] text-[15px] text-ink-2">Every promise tested through the real code path. Open a guarantee to inspect what happened.</p></header>
    <BoundaryHeld />
    <RecordedPolicyProof />
    <OfflineProof />
    <ReliabilityProof />
    {verification.loading && !run ? <Skeleton className="h-36 w-full" /> : <SummaryBand run={currentRun} metrics={metrics.data} status={status.data} running={running} starting={starting} action={action} />}
    {metrics.error && <ErrorState compact error={metrics.error} title="Aggregate metrics could not refresh" onRetry={() => void metrics.refetch()} />}
    {status.error && !status.data && <ErrorState compact error={status.error} title="Current enforcement mode did not load" onRetry={() => void status.refetch()} />}
    <LiveEvidence status={status.data} region="injection" />
    <section aria-labelledby="matrix-title" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-3"><h2 id="matrix-title" className="text-xl font-semibold text-ink">Guarantee matrix</h2>{!running && run?.finished_at && run.started_at && <p className="text-xs text-ink-3">Ran {relativeTime(run.finished_at)} · took {formatDuration(new Date(run.finished_at).getTime() - new Date(run.started_at).getTime())}</p>}</div>
      {verification.error ? <ErrorState error={verification.error} title="Verification results could not refresh" onRetry={() => void verification.refetch()} /> : null}
      {verification.loading && !run ? <div className="space-y-2" role="status" aria-label="Loading guarantees">{Array.from({ length: 5 }, (_,i) => <Skeleton key={i} className="h-14 w-full" />)}</div> : !results.length ? <Panel><EmptyState icon={<ShieldCheck className="size-5" />} title={running ? 'Waiting for the first completed check' : 'The suite has not verified any guarantees yet'} description={running ? 'Checks appear as they finish. Follow elapsed time above; the active check is not reported.' : 'The suite checks the poisoned runbook, wrong tenants, forged digests, races, duplicates and expired grants. An operator can start it above.'} /></Panel> : <GuaranteeMatrix results={results} running={running} />}
      {currentRun && <Technical><Disclosure summary={<span className="flex items-center gap-2">Suite details <Badge>{currentRun.status}</Badge></span>}><p className="mb-3 break-all font-mono text-xs text-ink-3">{currentRun.verification_id}</p><pre className="max-h-72 overflow-auto rounded-xl bg-sunken p-3 font-mono text-xs text-ink-2">{JSON.stringify(currentRun.summary, null, 2)}</pre></Disclosure></Technical>}
    </section>
    <LiveEvidence status={status.data} />
    <Disclosure summary="Which layer stopped what">
      {metrics.loading && !metrics.data && !results.length ? <Skeleton className="h-24 w-full" /> : metrics.error && !metrics.data && !results.length ? <ErrorState compact error={metrics.error} title="Layer counts did not load" onRetry={() => void metrics.refetch()} /> : Object.values(layerCounts.counts).every(n => !n) ? <EmptyState title="No stops recorded yet" description="After a scenario or verification suite runs, each deciding layer’s count appears here." /> : <LayerBar counts={layerCounts.counts} source={layerCounts.source} />}
    </Disclosure>
    <MetricTiles metrics={metrics.data} error={metrics.error} onRetry={() => void metrics.refetch()} status={status.data} />
    <footer className="max-w-[75ch] space-y-2 text-[13px] leading-relaxed text-ink-3">
      <p>{(run?.enforcement_mode ?? status.data?.enforcement.mode) === 'offline' ? 'Suite ArmorIQ decisions are simulated locally, not responses from the live service; no latency is reported. VeerIQ and PostgreSQL checks still use the real database.' : (run?.enforcement_mode ?? status.data?.enforcement.mode) === 'live' ? 'Suite ArmorIQ decisions use the live service and SDK. Grant scope, data rules and approvals belong to VeerIQ; database checks belong to PostgreSQL.' : 'The suite’s enforcement mode has not been recorded.'} ArmorIQ binds tool names; VeerIQ binds argument values.</p>
      <p>A passing row proves the behavior on the demo data and these probes. It does not prove that no other path exists.</p>
    </footer>
  </div>
}
