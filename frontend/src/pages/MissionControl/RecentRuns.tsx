import { plainOutcome, runFacts } from './outcome'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, History } from 'lucide-react'
import type { Run, ScenarioSpec } from '@/api/types'
import { Technical } from '@/lib/detail'
import { plannerLabel } from '@/lib/labels'
import { Badge, Button, EmptyState, ErrorState, Panel, RunStatusPill, Skeleton, TimeAgo } from '@/components/ui'

export interface RecentRunsProps {
  runs: Run[] | undefined
  error: Error | undefined
  onRetry: () => void
  scenarios: ScenarioSpec[] | undefined
  onStart: () => void
  canStart: boolean
}

const PAGE = 5

export function RecentRuns({ runs, error, onRetry, scenarios, onStart, canStart }: RecentRunsProps) {
  const [all, setAll] = useState(false)
  const sorted = runs ? [...runs].sort((a, b) => b.created_at.localeCompare(a.created_at)) : undefined
  const shown = sorted ? (all ? sorted : sorted.slice(0, PAGE)) : undefined
  const title = (id: string) => scenarios?.find((s) => s.scenario_id === id)?.title ?? 'Recovery run'

  return (
    <Panel icon={<History className="size-4" />} title="Recent runs" subtitle="Open any run to replay what the agent did and what stopped it." flush>
      {error && !runs ? (
        <ErrorState compact error={error} title="Runs did not load" onRetry={onRetry} />
      ) : !shown ? (
        <div className="space-y-2 p-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <EmptyState
          compact
          icon={<History className="size-5" />}
          title="No runs yet"
          description="Pick a scenario above to launch the first one. Every run leaves a replayable record."
          action={
            canStart ? (
              <Button variant="secondary" size="sm" onClick={onStart}>
                Choose a scenario
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          <ul className="divide-y divide-line px-2 pb-2">
            {shown.map((r) => {
              const facts = runFacts(r)
              return (
                <li key={r.run_id}>
                  <Link
                    to={`/runs/${r.run_id}`}
                    className="group grid items-center gap-x-4 gap-y-1.5 rounded-xl px-3 py-3 transition-colors hover:bg-surface-2 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1.6fr)_auto]"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-ink">{title(r.scenario_id)}</span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-3">
                        <span>{plannerLabel(r.planner, r.planner_kind, r.metadata?.planner_label)}</span>
                        <Badge size="sm" tone={r.enforcement_mode === 'offline' ? 'hold' : 'neutral'} dashed={r.enforcement_mode === 'offline'}>
                          {r.enforcement_mode === 'offline' ? 'Simulated ArmorIQ' : 'Live ArmorIQ'}
                        </Badge>
                        <TimeAgo value={r.created_at} />
                      </span>
                    </span>
                    <span className="text-[13px] leading-snug text-ink-2">
                      {plainOutcome(r)}
                      {facts.length > 0 && <span className="mt-1 block text-xs text-ink-3">{facts.join(' · ')}</span>}
                      {r.outcome_summary && (
                        <Technical inline>
                          <span className="mt-1 block text-xs text-ink-3">{r.outcome_summary}</span>
                        </Technical>
                      )}
                    </span>
                    <span className="flex items-center justify-between gap-3 md:justify-end">
                      <RunStatusPill status={r.status} />
                      <ArrowUpRight className="size-4 text-ink-3 transition-colors group-hover:text-ink" aria-hidden />
                    </span>
                  </Link>
                </li>
              )
            })}
          </ul>
          {sorted && sorted.length > PAGE && (
            <div className="border-t border-line px-5 py-3">
              <Button variant="ghost" size="sm" onClick={() => setAll((v) => !v)}>
                {all ? 'Show fewer' : `Show all ${sorted.length} runs`}
              </Button>
            </div>
          )}
        </>
      )}
    </Panel>
  )
}
