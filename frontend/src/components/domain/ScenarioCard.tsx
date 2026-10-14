import { useId, useState } from 'react'
import { ArrowRight, ChevronDown } from 'lucide-react'
import type { ScenarioKind, ScenarioSpec } from '@/api/types'
import { cn } from '@/lib/cn'
import { Technical } from '@/lib/detail'
import { SCENARIO_KIND } from '@/lib/labels'
import { Badge, Button } from '@/components/ui'
import { Collapse } from '@/components/motion'

const PURPOSE: Record<ScenarioKind, string> = {
  flagship: 'The bad requests stop; two orders are repaired once and today’s decisions survive.',
  baseline: 'The repair commits once and every protected decision survives.',
  race: 'The stale repair stops; only the order still safe to repair is committed.',
  approval: 'The run pauses for Orion. Approval allows the repair; rejection changes nothing.',
  boundary: 'Fixed probes hit the real gates. The legitimate repair lands with zero forbidden effects; no model is involved.',
}

export interface ScenarioCardProps {
  completedIncident?: boolean
  scenario: ScenarioSpec
  onLaunch: (scenario: ScenarioSpec) => void
  /** Larger treatment with highlights. Defaults to true for the flagship scenario. */
  featured?: boolean
  /** True while the grant draft for this card is being created. */
  loading?: boolean
  disabled?: boolean
  /** Why the card cannot launch (shown instead of the button). */
  disabledReason?: string
  className?: string
}

/** Launcher card for one demo scenario. Launching drafts a grant for review; nothing runs yet. */
export function ScenarioCard({ scenario, onLaunch, featured, loading, disabled, disabledReason, className, completedIncident }: ScenarioCardProps) {
  const isFeatured = featured ?? scenario.kind === 'flagship'
  const [open, setOpen] = useState(false)
  const detailsId = useId()
  return (
    <article className={cn('border-b border-line py-4 last:border-b-0', className)}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-2"><h3 className={cn('font-semibold text-ink', isFeatured ? 'text-lg' : 'text-sm')}>{scenario.title}</h3>{isFeatured && <Badge color="var(--layer-armoriq)">{completedIncident ? 'Prepared example' : 'Start here'}</Badge>}{scenario.inject_annotation && <Badge tone="hold">Contains a poisoned note</Badge>}</div>
            <button type="button" aria-label={`${scenario.inject_annotation ? 'Read poisoned note' : 'Scenario details'} for ${scenario.title}`} aria-expanded={open} aria-controls={detailsId} onClick={() => setOpen(v => !v)} className="-my-2 inline-flex min-h-11 shrink-0 items-center gap-1 rounded-lg px-2 text-[13px] font-medium text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink active:bg-surface-3">{scenario.inject_annotation ? 'Read poisoned note' : 'Scenario details'}<ChevronDown aria-hidden className={cn('size-3.5 transition-transform duration-150 motion-reduce:transition-none', open && 'rotate-180')} /></button>
          </div>
          <p className="mt-1 text-sm text-ink-2">{scenario.tagline}</p>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-3"><span className="font-medium text-ink-2">Expect: </span>{PURPOSE[scenario.kind]}</p>
          <Collapse open={open} id={detailsId}><div className="mt-3 space-y-2 border-t border-line pt-3"><p className="text-sm leading-relaxed text-ink-2">{scenario.description}</p><ul className="list-disc space-y-1 pl-4 text-[13px] text-ink-3">{scenario.highlights.map(h => <li key={h}>{h}</li>)}</ul><Technical><p className="break-words text-xs text-ink-3">{SCENARIO_KIND[scenario.kind]} · {scenario.scenario_id} · {scenario.default_planner}</p><p className="mt-1 text-sm text-ink-2">{scenario.expected_outcome}</p></Technical></div></Collapse>
        </div>
        <div className="shrink-0 sm:max-w-56">{disabledReason ? <p className="text-xs leading-relaxed text-ink-3">{disabledReason}</p> : <Button className="max-sm:min-h-11" variant={isFeatured ? 'primary' : 'secondary'} size="sm" loading={loading} disabled={disabled} onClick={() => onLaunch(scenario)} iconRight={<ArrowRight className="size-3.5" />}>Review grant</Button>}</div>
      </div>
    </article>
  )
}
