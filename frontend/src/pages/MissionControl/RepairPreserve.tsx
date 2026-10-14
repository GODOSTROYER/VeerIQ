import { CheckCheck, Hammer, ShieldCheck } from 'lucide-react'
import type { InvariantCheck, SnapshotDiffRow } from '@/api/types'
import { pluralize } from '@/lib/format'
import { Badge, Button, EmptyState, ErrorState, Panel, Skeleton } from '@/components/ui'
import { OrderDiffTable, ProtectedChecklist } from '@/components/domain'

interface QueryBits<T> {
  data: T | undefined
  error: Error | undefined
  refetch: () => Promise<void>
}

export interface RepairPreserveProps {
  diff: QueryBits<SnapshotDiffRow[]>
  checks: QueryBits<InvariantCheck[]>
  onStart: () => void
}

/** The two halves of the story side by side: what is wrong (and fixable) and what is right (and must stay). */
export function RepairPreserve({ diff, checks, onStart }: RepairPreserveProps) {
  const damaged = diff.data?.filter((r) => r.condition === 'damaged') ?? []
  const guarded = checks.data?.filter((c) => c.category !== 'repair') ?? []
  const violated = guarded.filter((c) => c.status === 'violated').length

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Panel
        accent="var(--diff-bad)"
        icon={<Hammer className="size-4" />}
        title="Needs repair"
        subtitle={diff.data ? `${pluralize(damaged.length, 'order')} show wrong values. The snapshot holds the right ones.` : 'Comparing orders with the snapshot'}
        actions={
          damaged.length > 0 ? (
            <Button size="sm" variant="secondary" onClick={onStart}>
              Start recovery
            </Button>
          ) : undefined
        }
        flush
      >
        <div className="px-2 pb-3">
          {diff.error && !diff.data ? (
            <ErrorState compact error={diff.error} title="Orders did not load" onRetry={() => void diff.refetch()} />
          ) : !diff.data ? (
            <div className="space-y-3 px-3 py-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : damaged.length === 0 ? (
            <EmptyState
              compact
              icon={<CheckCheck className="size-5" />}
              title="Nothing to repair"
              description="Every order matches the snapshot, or was changed on purpose after it."
            />
          ) : (
            <OrderDiffTable rows={damaged} compact />
          )}
        </div>
      </Panel>

      <Panel
        accent="var(--outcome-allow)"
        icon={<ShieldCheck className="size-4" />}
        title="Must stay true"
        subtitle="Today&rsquo;s decisions. The repair is not allowed to undo any of them."
        actions={
          checks.data ? (
            violated > 0 ? (
              <Badge tone="bad">{pluralize(violated, 'violation')}</Badge>
            ) : guarded.length > 0 ? (
              <Badge tone="good" icon={<CheckCheck />}>
                All {guarded.length} preserved
              </Badge>
            ) : undefined
          ) : undefined
        }
      >
        {checks.error && !checks.data ? (
          <ErrorState compact error={checks.error} title="Protected checks did not load" onRetry={() => void checks.refetch()} />
        ) : !checks.data ? (
          <div className="space-y-2.5">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : guarded.length === 0 ? (
          <EmptyState compact title="No protected checks" description="The server returned no checks to guard." />
        ) : (
          <ProtectedChecklist checks={checks.data} exclude={['repair']} />
        )}
      </Panel>
    </div>
  )
}
