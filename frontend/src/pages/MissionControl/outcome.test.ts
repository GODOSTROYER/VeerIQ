import { describe, expect, it } from 'vitest'
import type { Run, RunStatus } from '@/api/types'
import { plainOutcome, runFacts } from './outcome'

function run(overrides: Partial<Run> = {}): Run {
  return {
    run_id: 'run-1',
    grant_id: 'AG-77',
    scenario_id: 'atlas-flagship',
    workflow: 'rewindsafe.recovery',
    planner: 'scripted',
    planner_kind: 'scripted',
    enforcement_mode: 'live',
    status: 'succeeded',
    outcome_summary: null,
    steps_used: 0,
    replans_used: 0,
    plan: null,
    fixture_generation: 1,
    created_by: 'operator',
    created_at: '2026-10-06T09:00:00Z',
    updated_at: '2026-10-06T09:10:00Z',
    finished_at: '2026-10-06T09:10:00Z',
    metadata: {},
    ...overrides,
  }
}

/** The shape build_outcome_summary() writes for a run that repaired two orders and had one request stopped. */
const REPAIRED_AND_STOPPED =
  'Repaired O-2041, O-2042 from approved snapshot snap-1 (6 fields restored in 2 commits). ' +
  'ArmorIQ blocked restore_access_grant: it is not in the signed recovery plan. ' +
  'All 5 protected-state checks held (deleted records stayed deleted, revoked access stayed revoked).'

describe('plainOutcome', () => {
  it('counts repaired orders, commits and stopped requests from the recorded summary', () => {
    expect(plainOutcome(run({ outcome_summary: REPAIRED_AND_STOPPED }))).toBe(
      '2 orders repaired in 2 commits. 1 bad request stopped. Today’s decisions kept.',
    )
  })

  it('uses singular forms for one order, one commit and one stopped request', () => {
    expect(
      plainOutcome(
        run({
          outcome_summary:
            'Repaired O-2041 from approved snapshot snap-1 (1 field restored in 1 commit). ' +
            'VeerIQ grant scope blocked apply_repair_manifest: the request was outside the grant.',
        }),
      ),
    ).toBe('1 order repaired in 1 commit. 1 bad request stopped.')
  })

  it('pluralises several stopped requests', () => {
    expect(
      plainOutcome(
        run({
          outcome_summary:
            'Repaired O-2041 from approved snapshot snap-1 (1 field restored in 1 commit). ' +
            'ArmorIQ blocked restore_access_grant: it is not in the signed recovery plan. ' +
            'VeerIQ grant scope blocked apply_repair_manifest: the request was outside the grant.',
        }),
      ),
    ).toBe('1 order repaired in 1 commit. 2 bad requests stopped.')
  })

  it('omits the commit clause when the summary does not state the commit count', () => {
    expect(plainOutcome(run({ outcome_summary: 'Repaired O-2041, O-2042 from approved snapshot snap-1.' }))).toBe(
      '2 orders repaired.',
    )
  })

  it('says no repair was committed when the summary says so', () => {
    expect(
      plainOutcome(run({ status: 'blocked', outcome_summary: 'No repair was committed; application data was not changed by this run.' })),
    ).toBe('No repair committed. Open the run to see what stopped it.')
  })

  it('falls back to a status sentence when there is no summary, and never prints n/a or null', () => {
    const expected: Array<[RunStatus, string]> = [
      ['succeeded', 'Recovery completed. Open the run to inspect the repair.'],
      ['partially_succeeded', 'Part of the recovery completed. Open the run to see what remains.'],
      ['blocked', 'Recovery stopped before completion. Inspect the deciding gate.'],
      ['failed', 'The run failed. Open it to inspect the cause.'],
      ['cancelled', 'The run was cancelled. Its recorded steps remain available.'],
      ['executing', 'Recovery is in progress. Open the run to follow its next step.'],
    ]
    for (const [status, text] of expected) {
      const copy = plainOutcome(run({ status, outcome_summary: null }))
      expect(copy, status).toBe(text)
      expect(copy, status).not.toMatch(/n\/a|null|undefined/i)
    }
  })
})

describe('runFacts', () => {
  it('lists the restored fields, steps and replans that were recorded', () => {
    expect(
      runFacts(run({ outcome_summary: REPAIRED_AND_STOPPED, steps_used: 7, replans_used: 2 })),
    ).toEqual(['6 fields restored', '7 steps', '2 replans'])
  })

  it('uses the singular for one restored field, one step and one replan', () => {
    expect(
      runFacts(run({ outcome_summary: 'Repaired O-2041 from approved snapshot snap-1 (1 field restored in 1 commit).', steps_used: 1, replans_used: 1 })),
    ).toEqual(['1 field restored', '1 step', '1 replan'])
  })

  it('leaves out any piece whose source is absent or zero, rather than printing it as n/a or 0', () => {
    expect(runFacts(run({ outcome_summary: null, steps_used: 0, replans_used: 0 }))).toEqual([])
    expect(runFacts(run({ outcome_summary: 'No repair was committed; application data was not changed by this run.', steps_used: 3 }))).toEqual([
      '3 steps',
    ])
  })
})
