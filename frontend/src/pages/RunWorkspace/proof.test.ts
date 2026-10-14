import { describe, expect, it } from 'vitest'
import type { Decision, ExecutionReceipt, InvariantCheck, Run, RunEvent, TaskGrant } from '@/api/types'
import type { EnforcementFacts } from '@/lib/layers'
import { buildRunView } from './model'
import {
  buildProof,
  decisionChecks,
  externalSentence,
  isHeld,
  recordedProtectedChecks,
  repairedOrders,
  stoppedGroups,
  targetOrders,
  unrepairedOrders,
  type ProofLine,
} from './proof'

/* ─── Typed fixtures with sensible defaults ─── */

function check(overrides: Partial<InvariantCheck> = {}): InvariantCheck {
  return {
    check_id: 'tombstone:O-2041',
    label: 'Deleted record stayed deleted',
    category: 'tombstone',
    status: 'preserved',
    detail: '',
    evidence: {},
    ...overrides,
  }
}

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    decision_id: 'dec-1',
    run_id: 'run-1',
    proposal_id: 'prop-1',
    layer: 'grant',
    source: 'rewindsafe.grant_scope',
    outcome: 'block',
    decisive: false,
    shadow: false,
    simulated: false,
    reason: 'Tool is not in the grant',
    invariant: null,
    latency_ms: null,
    sponsor: null,
    evidence: {},
    created_at: '2026-10-06T09:02:00Z',
    ...overrides,
  }
}

function event(seq: number, type: string, overrides: Partial<RunEvent> = {}): RunEvent {
  return {
    seq,
    run_id: 'run-1',
    ts: `2026-10-06T09:${String(seq).padStart(2, '0')}:00Z`,
    type,
    actor: 'agent',
    title: type,
    detail: '',
    proposal_id: null,
    decision: null,
    data: {},
    ...overrides,
  }
}

function receipt(overrides: Partial<ExecutionReceipt> = {}): ExecutionReceipt {
  return {
    operation_id: 'op-1',
    idempotency_key: 'idem-1',
    grant_id: 'AG-77',
    run_id: 'run-1',
    manifest_id: 'man-1',
    manifest_digest: 'sha256:m1',
    result: 'committed',
    changes: [],
    checks: [],
    effect_counts: {},
    decision_sources: [],
    enforcement_mode: 'live',
    sdk_version: null,
    fixture_generation: 1,
    approval_id: null,
    created_at: '2026-10-06T09:05:00Z',
    committed_at: '2026-10-06T09:05:01Z',
    receipt_digest: 'sha256:3f9c1a2b4d5e6f70aabbccdd11223344ab12',
    ...overrides,
  }
}

function grant(overrides: Partial<TaskGrant> = {}): TaskGrant {
  return {
    grant_id: 'AG-77',
    workflow: 'rewindsafe.recovery',
    scenario_id: 'atlas-flagship',
    principal: 'svc-legacy-sync',
    principal_email: 'svc-legacy-sync@example.test',
    tenant_id: 'atlas',
    incident_id: 'INC-1',
    purpose: 'Repair O-2041 and O-2042',
    allowed_tools: ['inspect_snapshot', 'apply_repair_manifest'],
    resources: { order: ['O-2041', 'O-2042'] },
    reviewable: {},
    fields: ['total_cents', 'status'],
    prohibited_effects: [],
    source_constraints: {},
    limits: {
      max_commits: 1,
      max_rows_per_commit: 2,
      max_steps: 10,
      max_replans: 1,
      approval_ttl_seconds: 1200,
      review_threshold_cents: 100000,
    },
    status: 'active',
    commits_used: 0,
    created_at: '2026-10-06T09:00:00Z',
    expires_at: '2026-10-06T10:00:00Z',
    authorized_at: null,
    authorized_by: null,
    fixture_generation: 1,
    grant_digest: 'sha256:g1',
    ...overrides,
  }
}

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

const LIVE: EnforcementFacts = {
  enforcement_mode: 'live',
  plan: { mode: 'live', simulated: false },
  decisions: [{ simulated: false }],
}

const nameOf = (id: string | null | undefined): string => (id ? `Reviewer ${id}` : 'someone')

type ProofArgs = Parameters<typeof buildProof>[0]

/** Builds the proof for a set of events, with a finished live run unless the options say otherwise. */
function proof(events: RunEvent[], options: Partial<Omit<ProofArgs, 'view'>> = {}): ProofLine[] {
  return buildProof({
    view: buildRunView(events),
    run: run(),
    grant: grant(),
    checks: undefined,
    metrics: undefined,
    live: false,
    nameOf,
    enforcement: LIVE,
    ...options,
  })
}

/** An attempt by the agent that was refused. By default ArmorIQ's signed plan refused it. */
function blockedAttempt(
  seq: number,
  proposalId: string,
  tool = 'restore_access_grant',
  overrides: Partial<Decision> = {},
): RunEvent[] {
  return [
    event(seq, 'agent.proposal', { proposal_id: proposalId, data: { tool, arguments: { grant_id: 'AG-77' } } }),
    event(seq + 1, 'decision', {
      proposal_id: proposalId,
      decision: decision({
        decision_id: `dec-${proposalId}`,
        layer: 'armoriq',
        source: 'armoriq.sdk.plan_binding',
        outcome: 'block',
        decisive: true,
        invariant: 'tool_not_granted',
        reason: `tool-not-in-plan: '${tool}'`,
        ...overrides,
      }),
    }),
  ]
}

/* ─── Small predicates ─── */

describe('isHeld and decisionChecks', () => {
  it('counts a preserved or repaired check as held, and a pending or violated one as not held', () => {
    expect(isHeld(check({ status: 'preserved' }))).toBe(true)
    expect(isHeld(check({ status: 'repaired' }))).toBe(true)
    expect(isHeld(check({ status: 'pending' }))).toBe(false)
    expect(isHeld(check({ status: 'violated' }))).toBe(false)
  })

  it('leaves out the repair itself and the other tenant when asking what guards today’s decisions', () => {
    const kept = decisionChecks([
      check({ category: 'repair' }),
      check({ category: 'tenant_isolation' }),
      check({ category: 'tombstone' }),
      check({ category: 'access' }),
      check({ category: 'later_update' }),
      check({ category: 'hold' }),
    ])
    expect(kept.map((c) => c.category)).toEqual(['tombstone', 'access', 'later_update', 'hold'])
  })
})

/* ─── Recorded protected-state evidence ─── */

describe('recordedProtectedChecks', () => {
  it('reads checks recorded at run completion, with the time they were observed', () => {
    const view = buildRunView([
      event(1, 'run.finished', {
        data: {
          status: 'succeeded',
          protected_checks: [check()],
          protected_check_observation: { observed_at: '2026-10-06T09:09:00Z' },
        },
      }),
    ])
    expect(recordedProtectedChecks(view)).toMatchObject({
      source: 'run_finished',
      observedAt: '2026-10-06T09:09:00Z',
      checks: [expect.objectContaining({ check_id: 'tombstone:O-2041' })],
    })
  })

  it('also accepts run-completion checks wrapped in an object with a checks field', () => {
    const view = buildRunView([event(1, 'run.finished', { data: { protected_checks: { checks: [check()] } } })])
    expect(recordedProtectedChecks(view)?.source).toBe('run_finished')
  })

  it('falls back to the latest committed receipt, and reports nothing when no checks were recorded', () => {
    const view = buildRunView([
      event(1, 'execution.committed', { data: { receipt: receipt({ operation_id: 'op-1', checks: [check({ check_id: 'old' })] }) } }),
      event(2, 'execution.committed', {
        data: { receipt: receipt({ operation_id: 'op-2', committed_at: '2026-10-06T09:06:00Z', checks: [check({ check_id: 'latest' })] }) },
      }),
    ])
    expect(recordedProtectedChecks(view)).toEqual({
      checks: [expect.objectContaining({ check_id: 'latest' })],
      source: 'receipt',
      observedAt: '2026-10-06T09:06:00Z',
    })
    expect(recordedProtectedChecks(buildRunView([]))).toBeUndefined()
  })
})

/* ─── Statements for a person ─── */

describe('buildProof', () => {
  it('says how many protected checks were preserved when run completion recorded them', () => {
    const lines = proof([
      event(1, 'run.finished', {
        data: {
          status: 'succeeded',
          protected_checks: [
            check({ check_id: 'tombstone:O-2041' }),
            check({ check_id: 'access:AG-77', category: 'access', label: 'Revoked access stayed revoked' }),
            check({ check_id: 'later:O-2042', category: 'later_update', label: 'Later legitimate edit kept' }),
          ],
        },
      }),
    ])
    const statement = lines.find((l) => l.text.includes('protected-state checks'))
    expect(statement?.text).toContain('All 3 protected-state checks were recorded as preserved at run completion')
    expect(lines.some((l) => l.text.includes('violated'))).toBe(false)
  })

  it('names a violated check and never summarises the run as all held', () => {
    const lines = proof([event(1, 'run.finished', { data: { status: 'failed', protected_checks: [check({ status: 'violated' }), check({ check_id: 'access:AG-77', category: 'access' })] } })])
    expect(lines.find((l) => l.text.startsWith('Protected state was violated'))?.text).toBe(
      'Protected state was violated: Deleted record stayed deleted.',
    )
    expect(lines.some((l) => /All \d+ protected-state checks/.test(l.text))).toBe(false)
  })

  it('says how many checks hold when some are not yet confirmed', () => {
    const lines = proof([
      event(1, 'run.finished', {
        data: {
          status: 'partially_succeeded',
          protected_checks: [check(), check({ check_id: 'access:AG-77', category: 'access' }), check({ check_id: 'hold:O-2042', category: 'hold', status: 'pending' })],
        },
      }),
    ])
    expect(lines.find((l) => l.text.includes('protected-state checks hold'))?.text).toBe(
      '2 of 3 protected-state checks hold; the remaining checks are not yet confirmed.',
    )
  })

  it('does not count a repair check as protected state', () => {
    const lines = proof([
      event(1, 'run.finished', {
        data: {
          status: 'succeeded',
          protected_checks: [
            check({ check_id: 'repair:O-2041', category: 'repair', label: 'Repaired O-2041', status: 'pending' }),
            check({ check_id: 'tombstone:O-2041' }),
            check({ check_id: 'access:AG-77', category: 'access' }),
          ],
        },
      }),
    ])
    expect(lines.find((l) => l.text.includes('protected-state checks'))?.text).toContain('All 2 protected-state checks')
  })

  it('describes current checks as holding right now while a run is still in progress', () => {
    const lines = proof([], { live: true, checks: [check(), check({ check_id: 'access:AG-77', category: 'access' })] })
    expect(lines.find((l) => l.text.includes('protected-state checks'))?.text).toContain(
      'All 2 protected-state checks hold right now',
    )
    expect(lines.some((l) => l.text.startsWith('This run is still in progress'))).toBe(true)
  })

  it('does not certify a finished run with checks read from the current data after a demo reset', () => {
    const lines = proof([], { live: false, generationMismatch: true, checks: [check(), check({ check_id: 'access:AG-77', category: 'access' })] })
    expect(lines.some((l) => l.text.includes('hold right now'))).toBe(false)
    expect(lines.some((l) => l.text.includes('Current data cannot certify the past.'))).toBe(true)
  })

  it('summarises a tool blocked on every attempt once, with its layer and the check it broke', () => {
    const lines = proof([...blockedAttempt(1, 'prop-1'), ...blockedAttempt(3, 'prop-2')])
    expect(lines.find((l) => l.text.startsWith('“Restore access grant”'))?.text).toBe(
      '“Restore access grant” was attempted twice and blocked every time by ArmorIQ signed-plan binding (Tool not in the grant). Nothing was changed by the blocked attempt.',
    )
  })

  it('says how many attempts were blocked when only some were', () => {
    const veeriqGrant: Partial<Decision> = { layer: 'grant', source: 'rewindsafe.grant_scope', invariant: null }
    const lines = proof([
      ...blockedAttempt(1, 'prop-1', 'apply_repair_manifest', veeriqGrant),
      ...blockedAttempt(3, 'prop-2', 'apply_repair_manifest', veeriqGrant),
      event(5, 'agent.proposal', { proposal_id: 'prop-3', data: { tool: 'apply_repair_manifest' } }),
    ])
    expect(lines.find((l) => l.text.startsWith('“Apply repair”'))?.text).toBe(
      '“Apply repair” was attempted 3 times; 2 of those were blocked by the VeerIQ grant scope. Nothing was changed by the blocked attempt.',
    )
  })

  it('states the rows a committed repair changed and a shortened receipt digest', () => {
    const lines = proof([
      event(1, 'execution.committed', {
        data: {
          receipt: receipt({
            changes: [
              { row_id: 'O-2041', field: 'total_cents', before: 0, after: 124000 },
              { row_id: 'O-2041', field: 'status', before: 'damaged', after: 'healthy' },
              { row_id: 'O-2042', field: 'status', before: 'damaged', after: 'healthy' },
            ],
            effect_counts: { rows_updated: 2 },
          }),
        },
      }),
    ])
    const commit = lines.find((l) => l.text.startsWith('One repair was committed'))
    expect(commit?.text).toBe('One repair was committed in a single transaction: 2 rows updated (O-2041 and O-2042).')
    expect(commit?.technicalText).toBe('Receipt digest: sha256:3f9c1a2b…ab12.')
  })

  it('names an order left unrepaired in a partial run with the external change that stopped it', () => {
    const lines = proof(
      [
        event(1, 'execution.committed', {
          data: { receipt: receipt({ changes: [{ row_id: 'O-2041', field: 'total_cents', before: 0, after: 124000 }] }) },
        }),
        event(2, 'external.change', {
          title: 'Hold placed',
          data: { actor_label: 'Finance (dispute desk)', action: 'place_hold', target: 'O-2042', reason: 'dispute open' },
        }),
      ],
      { run: run({ status: 'partially_succeeded' }) },
    )
    expect(lines.find((l) => l.text.startsWith('O-2042 was not repaired'))?.text).toBe(
      'O-2042 was not repaired: Finance (dispute desk) placed a hold on O-2042 (dispute open) after the repair was previewed, so the repair was not applied to it.',
    )
  })

  it('discloses simulated enforcement and says which checks were still real', () => {
    const lines = proof([], { enforcement: { enforcement_mode: 'offline' } })
    const disclosure = lines.find((l) => l.text.startsWith('Enforcement was simulated for this run.'))
    expect(disclosure?.text).toContain('Grant, domain and PostgreSQL checks were real.')
  })

  it('makes no simulation claim for a run whose enforcement is live', () => {
    const lines = proof([], { enforcement: LIVE })
    expect(lines.some((l) => /simulat/i.test(l.text))).toBe(false)
  })
})

/* ─── Orders and grant targets ─── */

describe('unrepairedOrders and externalSentence', () => {
  it('gives an unrepaired order with no recorded cause a plain reason', () => {
    const view = buildRunView([
      event(1, 'execution.committed', { data: { receipt: receipt({ changes: [{ row_id: 'O-2041', field: 'total_cents', before: 0, after: 1 }] }) } }),
    ])
    expect(unrepairedOrders(grant(), view)).toEqual([
      { orderId: 'O-2042', reason: 'No repair was committed for it during this run.' },
    ])
  })

  it('uses the rejection that names the order as the reason it was not repaired', () => {
    const view = buildRunView([
      event(1, 'execution.rejected', { detail: 'Preconditions changed for O-2042 after preview', data: { manifest_id: 'man-1' } }),
    ])
    expect(unrepairedOrders(grant(), view).find((u) => u.orderId === 'O-2042')?.reason).toBe(
      'Preconditions changed for O-2042 after preview',
    )
  })

  it('describes a third-party action from the event’s own fields, and falls back to its title when a field is missing', () => {
    expect(externalSentence({ actor_label: 'Ops', action: 'revoke_access', target: 'svc-legacy-sync' }, 'Access revoked')).toBe(
      'Ops revoked access for svc-legacy-sync',
    )
    expect(externalSentence({ action: 'place_hold', target: 'O-2042' }, 'External hold')).toBe('External hold')
    expect(externalSentence({ actor_label: 'Ops', action: 'delete_everything', target: 'O-2042' }, 'Unknown change')).toBe(
      'Unknown change',
    )
  })

  it('lists granted and reviewable orders once each as the run targets', () => {
    expect(targetOrders(grant({ resources: { order: ['O-2041', 'O-2042'] }, reviewable: { order: ['O-2042', 'O-2043'] } }))).toEqual([
      'O-2041',
      'O-2042',
      'O-2043',
    ])
    expect(targetOrders(undefined)).toEqual([])
  })
})

describe('stoppedGroups', () => {
  it('groups blocked attempts by tool, lists the layers outermost first, and flags which were simulated', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'restore_access_grant' } }),
      event(2, 'decision', {
        proposal_id: 'prop-1',
        decision: decision({ decision_id: 'dec-sim', layer: 'armoriq', source: 'armoriq.offline_simulation', simulated: true, decisive: true, outcome: 'block' }),
      }),
      event(3, 'decision', {
        proposal_id: 'prop-1',
        decision: decision({ decision_id: 'dec-grant', layer: 'grant', source: 'rewindsafe.grant_scope', simulated: false, decisive: false, outcome: 'block' }),
      }),
    ])
    expect(stoppedGroups(view)).toEqual([
      {
        tool: 'restore_access_grant',
        attempts: 1,
        blocked: 1,
        layers: [
          { layer: 'armoriq', simulated: true },
          { layer: 'grant', simulated: false },
        ],
        armoriq: true,
      },
    ])
  })

  it('does not count a shadow block as a layer that stopped the request', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'restore_access_grant' } }),
      event(2, 'decision', {
        proposal_id: 'prop-1',
        decision: decision({ decision_id: 'dec-shadow', layer: 'armoriq', source: 'armoriq.backend.enforce', shadow: true, outcome: 'block' }),
      }),
      event(3, 'decision', { proposal_id: 'prop-1', decision: decision({ decision_id: 'dec-grant', decisive: true }) }),
    ])
    const [group] = stoppedGroups(view)
    expect(group?.layers.map((l) => l.layer)).toEqual(['grant'])
    expect(group?.armoriq).toBe(false)
  })
})

describe('repairedOrders', () => {
  it('restores the total change per order, and leaves the amount undefined when the total did not change', () => {
    const view = buildRunView([
      event(1, 'execution.committed', {
        data: {
          receipt: receipt({
            changes: [
              { row_id: 'O-2041', field: 'total_cents', before: 0, after: 124000 },
              { row_id: 'O-2041', field: 'status', before: 'damaged', after: 'healthy' },
              { row_id: 'O-2042', field: 'status', before: 'damaged', after: 'healthy' },
            ],
          }),
        },
      }),
    ])
    expect(repairedOrders(view)).toEqual([
      { orderId: 'O-2041', restoredCents: 124000 },
      { orderId: 'O-2042', restoredCents: undefined },
    ])
  })
})
