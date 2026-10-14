import type { AppState, InvariantCheck, SnapshotDiffRow } from '@/api/types'
import { OrderDiffTable, ProtectedChecklist } from '@/components/domain'
import { Digest, Disclosure, EmptyState, ErrorState, KeyValue, KeyValueGrid, NumberRoll, Skeleton } from '@/components/ui'
import { Technical } from '@/lib/detail'
import { formatDateTime, formatMoney, pluralize } from '@/lib/format'
import { damagedValueCents } from './IncidentCard'
import { buildRibbonEvents } from './TimeRibbon'

interface Query<T> { data: T | undefined; error: Error | undefined; refetch: () => Promise<void> }

/** One picture of the recovery boundary; the exact evidence remains one reveal away. */
export function IncidentOverview({ state, diff, checks }: { state: Query<AppState>; diff: Query<SnapshotDiffRow[]>; checks: Query<InvariantCheck[]> }) {
  const error = (!state.data && state.error) || (!diff.data && diff.error) || (!checks.data && checks.error)
  if (error) return <ErrorState compact error={error} title="The incident comparison did not load" onRetry={() => void Promise.all([state.refetch(), diff.refetch(), checks.refetch()])} />
  if (!state.data || !diff.data || !checks.data) return <section aria-label="Loading incident comparison" role="status" className="rounded-2xl border border-line bg-raised p-5 space-y-4"><Skeleton className="h-5 w-3/4" /><Skeleton className="h-10 w-full" /><div className="grid grid-cols-2 gap-4"><Skeleton className="h-28" /><Skeleton className="h-28" /></div><Skeleton className="h-8 w-full" /></section>
  const app = state.data
  const rows = diff.data
  const damaged = rows.filter(r => r.condition === 'damaged')
  const guarded = checks.data.filter(c => c.category !== 'repair')
  const events = buildRibbonEvents(app, rows)
  const decisions = events.filter(e => e.kind === 'decision')
  const lost = damagedValueCents(rows)
  return <section aria-labelledby="incident-title" className="min-w-0 rounded-2xl border border-line bg-raised p-4 sm:p-5">
    <h2 id="incident-title" className="text-base font-semibold text-ink">{app.incident.title}</h2><p className="mt-2 text-[13px] leading-relaxed text-ink-2">{app.incident.description}</p>
    <ol aria-label="Incident time axis" className="mt-4 grid grid-cols-4 gap-2 border-b border-line pb-4 text-xs">
      {['Snapshot', 'Damage', 'Later decisions', 'Now'].map((label, i) => <li key={label} className="min-w-0"><div className="mb-2 flex items-center gap-2" aria-hidden><span className="size-2 shrink-0 rounded-full" style={{ background: i === 1 ? 'var(--diff-bad)' : i === 2 ? 'var(--diff-keep)' : 'var(--text-2)' }} /><span className="h-px flex-1 bg-line-strong" /></div><span className="font-medium text-ink">{label}</span><span className="mt-1 block text-ink-3">{['Approved values', 'Wrong order values', `${decisions.length} changes to keep`, 'Repair only damage'][i]}</span></li>)}
    </ol>
    <dl className="mt-4 divide-y divide-line">
      <div className="grid gap-2 py-3 sm:grid-cols-[140px_minmax(0,1fr)]">
        <dt className="text-sm font-medium" style={{ color: 'var(--diff-bad)' }}>Damaged</dt>
        <dd className="text-sm text-ink-2">{damaged.length ? <>{pluralize(damaged.length, 'order')} · <NumberRoll value={lost} format={n => formatMoney(Math.round(n))} /> in missing totals.<span className="mt-1 block text-xs text-ink-3">{damaged.map(r => r.order_id).join(', ')}</span></> : 'No damaged orders remain. Open the walkthrough to see the poisoned request stopped.'}</dd>
      </div>
      <div className="grid gap-2 py-3 sm:grid-cols-[140px_minmax(0,1fr)]">
        <dt className="text-sm font-medium text-ink">Repair permitted</dt>
        <dd className="text-sm text-ink-2">Only the orders and damaged fields you authorize. Values come from the approved snapshot.<span className="mt-1 block text-xs text-ink-3">Review exact scope before execution. A snapshot cannot grant new permissions.</span></dd>
      </div>
      <div className="grid gap-2 py-3 sm:grid-cols-[140px_minmax(0,1fr)]">
        <dt className="text-sm font-medium" style={{ color: 'var(--diff-keep)' }}>Must stay unchanged</dt>
        <dd>{guarded.length ? <ProtectedChecklist checks={guarded} compact /> : <EmptyState compact title="No protected checks returned" description="Retry the comparison to see which decisions the repair must preserve." />}</dd>
      </div>
    </dl>
    <div className="mt-4 border-t border-line pt-2">
      <Disclosure summary="Compare current orders with the snapshot">
        <OrderDiffTable rows={rows} compact emptyState={<EmptyState compact title="No orders to compare" description="This tenant has no orders in the approved snapshot." />} />
        <div className="mt-4"><ProtectedChecklist checks={guarded} /></div>
      </Disclosure>
    </div>
    <p className="mt-4 border-t border-line pt-3 text-xs leading-relaxed text-ink-2">Why later state matters: <a className="text-accent underline underline-offset-4" href="https://about.gitlab.com/blog/postmortem-of-database-outage-of-january-31/" target="_blank" rel="noreferrer">GitLab’s 2017 postmortem</a> describes lost database changes after recovery from a six-hour-old snapshot. Our example models four reversed decisions; it does not claim VeerIQ could recover GitLab’s missing data.</p>
    <Technical><div className="mt-3 border-t border-line pt-3 space-y-4">
      <KeyValueGrid columns={2}><KeyValue label="Incident" mono>{app.incident.incident_id}</KeyValue><KeyValue label="Tenant">{app.tenant.name}</KeyValue><KeyValue label="Approved snapshot" mono>{app.snapshot.snapshot_id}</KeyValue><KeyValue label="Approved by">{app.snapshot.approved_by || 'Not recorded'}</KeyValue><KeyValue label="Snapshot digest"><Digest value={app.snapshot.content_digest} label="snapshot digest" /></KeyValue></KeyValueGrid>
      <ol className="space-y-1 text-xs text-ink-2">{events.map(e => <li key={e.id} className="flex flex-wrap justify-between gap-2"><span>{e.label}</span><time dateTime={e.at}>{formatDateTime(e.at)}</time></li>)}</ol>
      <p className="text-xs text-ink-3">Restoring the whole snapshot would undo {pluralize(decisions.length, 'later decision')}. VeerIQ repairs only damaged fields.</p>
    </div></Technical>
  </section>
}
