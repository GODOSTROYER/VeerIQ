import type { Identity, ScenarioSpec } from '@/api/types'
import { Button, EmptyState, ErrorState, Skeleton } from '@/components/ui'
import { ScenarioCard } from '@/components/domain'

export interface ScenarioLauncherProps {
  scenarios: ScenarioSpec[] | undefined
  error: Error | undefined
  onRetry: () => void
  identity: Identity
  repaired?: boolean
  launchingId: string | null
  onLaunch: (s: ScenarioSpec) => void
}

/** The flagship leads a compact list; every scenario opens grant review. */
export function ScenarioLauncher({ scenarios, error, onRetry, identity, launchingId, onLaunch, repaired }: ScenarioLauncherProps) {
  if (error && !scenarios) return <ErrorState error={error} title="Scenarios did not load" onRetry={onRetry} />
  if (!scenarios) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-28 rounded-xl" />
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-20 rounded-xl" />
        ))}
      </div>
    )
  }

  const flagship = scenarios.find((s) => s.kind === 'flagship')
  const rest = scenarios.filter((s) => s !== flagship)
  const reason = identity.tenant_id !== 'atlas' ? 'These recovery examples belong to Atlas. Return to the incident operator to review a grant.' : identity.role !== 'operator' ? 'Only an operator can start a recovery. Reviewers approve repairs from the Approvals page.' : undefined

  const card = (s: ScenarioSpec, featured: boolean) => (
    <ScenarioCard
      scenario={s}
      featured={featured}
      completedIncident={repaired}
      onLaunch={onLaunch}
      loading={launchingId === s.scenario_id}
      disabled={launchingId !== null && launchingId !== s.scenario_id}
      disabledReason={reason}
    />
  )

  if (!scenarios.length) return <EmptyState title="No scenarios available" description="Retry to load the recovery examples for this tenant." action={<Button variant="secondary" size="sm" onClick={onRetry}>Reload scenarios</Button>} />
  return <div className="min-w-0 rounded-2xl border border-line bg-raised px-4 sm:px-5">{flagship && card(flagship, true)}{rest.map(s => <div key={s.scenario_id}>{card(s, false)}</div>)}</div>
}
