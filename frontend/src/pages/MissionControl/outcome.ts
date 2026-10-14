import type { Run } from '@/api/types'
import { pluralize } from '@/lib/format'

/** The recorded "(4 fields restored in 1 commit)" count inside outcome_summary. */
const FIELDS_RESTORED = /\((\d+) fields? restored/
/** One "<layer> blocked <tool>: <reason>" clause per distinct stopped request. */
const BLOCKED_STEP = / blocked [a-z0-9_]+: /g

/** Short copy derived only from the run's recorded status and outcome. Exact copy stays in Technical. */
export function plainOutcome(run: Run): string {
  const raw = run.outcome_summary ?? ''
  const repair = raw.match(/^Repaired (.+?) from approved snapshot/)
  const count = repair?.[1].match(/O-\d+/g)?.length
  const commits = raw.match(/in (\d+) commit/)
  const blocked = raw.match(BLOCKED_STEP)?.length ?? 0
  if (count) return `${count} ${count === 1 ? 'order' : 'orders'} repaired${commits ? ` in ${commits[1]} ${commits[1] === '1' ? 'commit' : 'commits'}` : ''}.${blocked ? ` ${pluralize(blocked, 'bad request')} stopped.` : ''}${raw.includes('checks held') ? ' Today’s decisions kept.' : ''}`
  if (raw.includes('No repair was committed')) return 'No repair committed. Open the run to see what stopped it.'
  const copy: Partial<Record<Run['status'], string>> = {
    succeeded: 'Recovery completed. Open the run to inspect the repair.',
    partially_succeeded: 'Part of the recovery completed. Open the run to see what remains.',
    blocked: 'Recovery stopped before completion. Inspect the deciding gate.',
    failed: 'The run failed. Open it to inspect the cause.',
    cancelled: 'The run was cancelled. Its recorded steps remain available.',
  }
  return copy[run.status] ?? 'Recovery is in progress. Open the run to follow its next step.'
}

/** Recorded numbers that tell runs of one scenario apart. A piece is left out when its source is absent. */
export function runFacts(run: Run): string[] {
  const restored = Number(run.outcome_summary?.match(FIELDS_RESTORED)?.[1] ?? 0)
  const facts: string[] = []
  if (restored > 0) facts.push(`${pluralize(restored, 'field')} restored`)
  if (run.steps_used > 0) facts.push(pluralize(run.steps_used, 'step'))
  if (run.replans_used > 0) facts.push(pluralize(run.replans_used, 'replan'))
  return facts
}
