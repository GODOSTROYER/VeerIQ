import reliabilitySummary from '../../data/reliabilitySummary.json'
import { Disclosure } from '@/components/ui'

interface ReliabilityTotals {
  trials: number
  acted: number
  never_acted: number
  interrupted: number
  poisoned_action_attempted: number
  poisoned_action_blocked: number
  repairs_completed: number
  forbidden_effects: number
  records_total?: number
  records_with_effect_observation?: number
  records_unknown_effect_status?: number
  blocked_by: Partial<Record<string, number>>
}

interface ReliabilityBatch extends ReliabilityTotals {
  file: string
  recorded_at: string
  provider: string
  models: string[]
  enforcement: string
}

interface ReliabilitySummary {
  schema: string
  scenario: string
  poisoned_tool: string
  caveat: string
  totals: ReliabilityTotals
  batches: ReliabilityBatch[]
}

const summary: ReliabilitySummary = reliabilitySummary
const t = summary.totals

const DAY = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

/** "12 Oct 2026". Batch timestamps carry microseconds; trim them so every engine parses the value. */
function recordedDay(iso: string): string {
  const d = new Date(iso.replace(/(\.\d{3})\d+/, '$1'))
  return Number.isNaN(d.getTime()) ? iso : DAY.format(d)
}

/** "armoriq.sdk.plan_binding" -> "ArmorIQ plan binding" */
function blockerNames(blocked: Partial<Record<string, number>>): string[] {
  return Object.keys(blocked).map(key => key.replace(/^armoriq\.(sdk\.)?/i, 'ArmorIQ ').replace(/[._-]+/g, ' ').trim())
}

function joinNames(names: string[]): string {
  return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

const models = [...new Set(summary.batches.flatMap(b => b.models))]
const allLive = summary.batches.every(b => b.enforcement === 'live')
/** Where the numbers come from, so they are never read as a result of the current local session. */
const provenance = `Recorded trials${models.length ? ` with ${joinNames(models)}` : ''}${allLive ? ' and live ArmorIQ enforcement' : ''}, not this session.`

const blockers = blockerNames(t.blocked_by)
const figures = [
  {
    value: `${t.poisoned_action_blocked} of ${t.poisoned_action_attempted}`,
    label: blockers.length ? `Attempts to re-enable a revoked account, blocked by ${joinNames(blockers)}` : 'Attempts to re-enable a revoked account',
  },
  { value: `${t.repairs_completed} of ${t.acted}`, label: 'Repairs completed in trials where the model acted' },
  { value: String(t.forbidden_effects), label: `Forbidden effects observed, in the ${t.records_with_effect_observation ?? t.trials} records with effect observations` },
]

/** The headline evidence: pooled recorded live trials, read from the generated summary file. */
export function BoundaryHeld() {
  return <section aria-labelledby="boundary-held-title" className="space-y-6 rounded-2xl border border-line bg-raised px-5 py-6 sm:px-6">
    <div className="space-y-1">
      <h2 id="boundary-held-title" className="text-xl font-semibold tracking-[-0.02em] text-ink">The boundary held against a live model</h2>
      <p className="text-sm text-ink-3">{provenance}</p>
    </div>
    <div className="grid gap-6 sm:grid-cols-3">
      {figures.map(f => <div key={f.label}>
        <p className="tabular text-4xl font-semibold tracking-[-0.03em] text-ink sm:text-5xl">{f.value}</p>
        <p className="mt-2 max-w-[28ch] text-sm leading-snug text-ink-2">{f.label}</p>
      </div>)}
    </div>
    <div className="space-y-2">
      <p className="text-sm text-ink-3">{t.trials} recorded trials, of which {t.never_acted} never acted (stopped by the model provider’s rate limit or the operator before the model proposed anything).{t.records_unknown_effect_status ? ` ${t.records_unknown_effect_status} interrupted ${t.records_unknown_effect_status === 1 ? 'record lacks' : 'records lack'} effect observations, so their effect status is unknown.` : ''}</p>
      <p className="max-w-[72ch] text-xs leading-relaxed text-ink-3">{summary.caveat}</p>
    </div>
    <Disclosure summary={`Results by batch · ${summary.batches.length} batches`}>
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Results by batch">
        <table className="w-full min-w-[640px] border-collapse text-left text-[13px]">
          <caption className="sr-only">Recorded trials in each batch</caption>
          <thead>
            <tr className="border-b border-line text-xs text-ink-3">
              <th scope="col" className="py-2 pr-4 font-medium">Recorded</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Trials</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Acted</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Attempted</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Blocked</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Completed</th>
              <th scope="col" className="py-2 pl-3 text-right font-medium">Forbidden effects</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {summary.batches.map(b => <tr key={b.file}>
              <th scope="row" className="py-3 pr-4 font-normal text-ink">{recordedDay(b.recorded_at)}<span className="block font-mono text-xs text-ink-3">{b.file}</span></th>
              <td className="tabular px-3 py-3 text-right text-ink-2">{b.trials}</td>
              <td className="tabular px-3 py-3 text-right text-ink-2">{b.acted}</td>
              <td className="tabular px-3 py-3 text-right text-ink-2">{b.poisoned_action_attempted}</td>
              <td className="tabular px-3 py-3 text-right text-ink-2">{b.poisoned_action_blocked}</td>
              <td className="tabular px-3 py-3 text-right text-ink-2">{b.repairs_completed}</td>
              <td className="tabular py-3 pl-3 text-right text-ink-2">{b.forbidden_effects}</td>
            </tr>)}
          </tbody>
        </table>
      </div>
    </Disclosure>
  </section>
}
