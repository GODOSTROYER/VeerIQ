import { Siren } from 'lucide-react'
import type { AppState, SnapshotDiffRow } from '@/api/types'
import { formatDateTime, formatMoney, pluralize } from '@/lib/format'
import { AnimatedNumber, Badge, Digest, ErrorState, KeyValue, Panel, Skeleton } from '@/components/ui'

export interface IncidentCardProps {
  state: AppState | undefined
  rows: SnapshotDiffRow[] | undefined
  error: Error | undefined
  onRetry: () => void
}

/** Value that the snapshot says should be there but the damaged orders now show as lost. */
export function damagedValueCents(rows: SnapshotDiffRow[]): number {
  return rows
    .filter((r) => r.condition === 'damaged' && r.current)
    .reduce((sum, r) => sum + Math.max(0, r.snapshot.total_cents - (r.current?.total_cents ?? 0)), 0)
}

export function IncidentCard({ state, rows, error, onRetry }: IncidentCardProps) {
  if (error && !state) {
    return (
      <Panel>
        <ErrorState compact error={error} title="The incident did not load" onRetry={onRetry} />
      </Panel>
    )
  }
  if (!state) {
    return (
      <Panel>
        <div className="space-y-3">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-7 w-3/4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      </Panel>
    )
  }

  const { incident, snapshot } = state
  const damaged = rows?.filter((r) => r.condition === 'damaged') ?? []
  const lost = rows ? damagedValueCents(rows) : 0

  return (
    <Panel accent="var(--diff-bad)">
      <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr] lg:gap-12">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="bad" icon={<Siren />} mono>
              {incident.incident_id}
            </Badge>
            <span className="text-xs text-ink-3">
              Started {formatDateTime(incident.started_at)}, detected {formatDateTime(incident.detected_at)}
            </span>
          </div>
          <h2 className="mt-3 text-2xl font-semibold leading-tight tracking-[-0.025em] text-ink">{incident.title}</h2>
          <p className="mt-2 max-w-prose text-[14px] leading-relaxed text-ink-2">{incident.description}</p>
        </div>

        <div className="grid grid-cols-2 content-start gap-x-6 gap-y-5">
          <div>
            <p className="text-xs text-ink-3">Order value reading as lost</p>
            <p className="mt-1 text-[28px] font-semibold leading-none tracking-[-0.03em] text-ink">
              <AnimatedNumber value={lost} format={(n) => formatMoney(Math.round(n))} />
            </p>
            <p className="mt-1.5 text-xs text-ink-3">{rows ? `Across ${pluralize(damaged.length, 'damaged order')} of ${state.tenant.name}` : 'Loading orders'}</p>
          </div>
          <KeyValue label="Approved snapshot" hint={`Taken ${formatDateTime(snapshot.taken_at)}${snapshot.approved_by ? `, approved by ${snapshot.approved_by}` : ''}`} mono>
            {snapshot.snapshot_id}
          </KeyValue>
          <KeyValue label="Snapshot digest" className="col-span-2">
            <Digest value={snapshot.content_digest} label="snapshot digest" head={12} tail={6} />
          </KeyValue>
        </div>
      </div>
    </Panel>
  )
}
