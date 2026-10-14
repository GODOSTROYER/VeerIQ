import type { Metrics, SystemStatus } from '@/api/types'
import { Badge, Disclosure, EmptyState, ErrorState, Skeleton } from '@/components/ui'
import { Technical } from '@/lib/detail'
export interface MetricTilesProps { metrics: Metrics | undefined; error: Error | undefined; onRetry: () => void; status: SystemStatus | undefined }
/** Historical export retained; metrics now live in a compact disclosure, never a tile row. */
export function MetricTiles({ metrics: m, error, onRetry, status }: MetricTilesProps) {
  if (error && !m) return <ErrorState compact error={error} title="Metrics did not load" onRetry={onRetry} />
  if (!m) return <Skeleton className="h-12 w-full" />
  if (!Object.keys(m).length) return <EmptyState title="No aggregate metrics recorded" description="Metrics appear after a scenario or verification suite records its results." />
  const simulated = status?.enforcement.simulated === true || m.simulated === true
  const legacy = m.armoriq_latency_ms?.by_source
  const enforce = m.armoriq?.enforce ?? legacy?.['armoriq.backend.enforce']
  const issuance = m.armoriq?.issuance ?? legacy?.['armoriq.backend.token_issuance']
  const timed = !simulated && (enforce?.count ?? 0) > 0
  const signed = !simulated && (issuance?.count ?? 0) > 0
  return <Disclosure summary="More metrics and timing notes">
    <dl className="grid gap-4 sm:grid-cols-2 text-[13px]">
      <div><dt className="text-ink-3">Replans after a stop</dt><dd className="mt-1 text-ink">{m.replans ?? m.safe_replans ?? 'Not recorded'} · times the agent adapted after a stop.</dd></div>
      <div><dt className="text-ink-3">Commits</dt><dd className="mt-1 text-ink">{m.commits ?? 'Not recorded'} · repairs written in one transaction.</dd></div>
    </dl>
    <p className="mt-3 text-xs text-ink-3">Attacks refused count proposals stopped before any effect. Forbidden effects count rows or authority changed against the rules.</p>
    <Technical><div className="mt-4 space-y-3 border-t border-line pt-4 text-[13px] text-ink-2">
      {simulated && <Badge tone="hold" dashed>Simulated timing · no network call</Badge>}
      <p><strong className="text-ink">ArmorIQ policy check (network): </strong>{timed && enforce?.p50 != null ? Math.round(enforce.p50) + ' ms median across ' + enforce.count + ' live checks' + (enforce.p95 != null ? '; 95th percentile ' + Math.round(enforce.p95) + ' ms.' : '.') : simulated ? 'Enforcement is simulated here, so there is nothing to time.' : 'No live ArmorIQ checks have been timed yet.'}</p>
      <p><strong className="text-ink">ArmorIQ plan signing: </strong>{signed && issuance?.p50 != null ? Math.round(issuance.p50) + ' ms median across ' + issuance.count + ' signed plans. Minted once per run.' : simulated ? 'Enforcement is simulated here, so there is nothing to time.' : 'Signed once per run. No live plan has been timed yet.'}</p>
      <p>Off-plan refusals are local SDK checks against the signed plan (0 ms, no network), so they are not counted in these timings. Plan signing, policy checks and local refusals are timed separately.</p>
      <Disclosure summary="Complete recorded metrics"><pre className="max-h-80 overflow-auto font-mono text-xs">{JSON.stringify(m, null, 2)}</pre></Disclosure>
    </div></Technical>
  </Disclosure>
}
