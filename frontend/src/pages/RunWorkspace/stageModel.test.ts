import { describe, expect, it } from 'vitest'
import type { Decision, ExecutionReceipt, InvariantCheck, RunEvent, RunStatus } from '@/api/types'
import type { EnforcementFacts } from '@/lib/layers'
import type { CardCtx } from './TimelineCards'
import { buildRunView, type RunView } from './model'
import {
  gateResult,
  pendingGate,
  recordedVerification,
  stopFor,
  terminalLabel,
} from './stageModel'

/* ─── Typed fixtures with sensible defaults ─── */

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    decision_id: 'dec-1',
    run_id: 'run-1',
    proposal_id: 'prop-1',
    layer: 'grant',
    source: 'rewindsafe.grant_scope',
    outcome: 'block',
    decisive: true,
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

function receipt(overrides: Partial<ExecutionReceipt> = {}): ExecutionReceipt {
  return {
    operation_id: 'op-1',
    idempotency_key: 'idem-1',
    grant_id: 'AG-77',
    run_id: 'run-1',
    manifest_id: 'man-1',
    manifest_digest: 'sha256:m1',
    result: 'committed',
    changes: [{ row_id: 'O-2041', field: 'total_cents', before: 0, after: 124000 }],
    checks: [],
    effect_counts: {},
    decision_sources: [],
    enforcement_mode: 'live',
    sdk_version: null,
    fixture_generation: 1,
    approval_id: null,
    created_at: '2026-10-06T09:05:00Z',
    committed_at: '2026-10-06T09:05:01Z',
    receipt_digest: 'sha256:r1',
    ...overrides,
  }
}

const LIVE: EnforcementFacts = { enforcement_mode: 'live', plan: { mode: 'live', simulated: false }, decisions: [{ simulated: false }] }

const names: Record<string, string> = { 'rev-1': 'Priya Shah' }

/** The render context a timeline card receives. Only the view and the name lookup matter to the stage model. */
function cardCtx(view: RunView): CardCtx {
  return {
    action: { accessPrincipal: () => undefined, manifestRows: () => [] },
    plan: undefined,
    run: undefined,
    grant: undefined,
    view,
    handlerEntries: undefined,
    nameOf: (id) => (id ? (names[id] ?? 'someone') : 'someone'),
    enforcement: LIVE,
    selectedId: undefined,
    onSelect: () => undefined,
    ticking: false,
    checks: undefined,
    checkEvidence: undefined,
    scenarioTitle: undefined,
    onExport: () => undefined,
    exporting: false,
    reviewAs: undefined,
  }
}

/** The first proposal in a view, which every test below asserts on. */
function firstProposal(view: RunView) {
  const proposal = view.proposals[0]
  if (!proposal) throw new Error('expected the view to contain a proposal')
  return proposal
}

/* ─── Which gate stopped a request ─── */

describe('stopFor', () => {
  it('stops a blocked request at the layer that blocked it', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'restore_access_grant' } }),
      event(2, 'decision', { proposal_id: 'prop-1', decision: decision() }),
    ])
    expect(stopFor(firstProposal(view), view)).toBe('grant')
  })

  it('stops a request held for a reviewer at the approval gate', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'apply_repair_manifest' } }),
      event(2, 'approval.requested', {
        proposal_id: 'prop-1',
        data: {
          approval: {
            approval_id: 'appr-1',
            run_id: 'run-1',
            grant_id: 'AG-77',
            proposal_id: 'prop-1',
            tool: 'apply_repair_manifest',
            manifest_id: 'man-1',
            payload_digest: 'sha256:p1',
            targets: ['O-2041'],
            reason: 'High-value repair',
            requested_by: 'agent',
            requested_at: '2026-10-06T09:02:00Z',
            expires_at: '2026-10-06T09:22:00Z',
            state_constraints: {},
            status: 'pending',
            decided_by: null,
            decided_at: null,
            note: null,
            sponsor_delegation_id: null,
            sponsor_status: null,
          },
        },
      }),
    ])
    expect(stopFor(firstProposal(view), view)).toBe('approval')
  })

  it('stops a stale commit at the database', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'apply_repair_manifest', arguments: { manifest_id: 'man-1' } } }),
      event(2, 'execution.rejected', { proposal_id: 'prop-1', detail: 'Preconditions changed', data: { manifest_id: 'man-1' } }),
    ])
    expect(stopFor(firstProposal(view), view)).toBe('postgres')
  })

  it('stops nothing for a request that ran', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'inspect_snapshot' } }),
      event(2, 'tool.result', { proposal_id: 'prop-1', data: { summary: 'Read snapshot' } }),
    ])
    expect(stopFor(firstProposal(view), view)).toBeUndefined()
  })
})

/* ─── Which gate is checked next ─── */

describe('pendingGate', () => {
  it('moves to the next gate after the last recorded pass, never inventing a pass', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'apply_repair_manifest' } }),
      event(2, 'decision', { proposal_id: 'prop-1', decision: decision({ decision_id: 'd-a', layer: 'armoriq', source: 'armoriq.sdk.plan_binding', outcome: 'allow', decisive: false }) }),
      event(3, 'decision', { proposal_id: 'prop-1', decision: decision({ decision_id: 'd-g', layer: 'grant', source: 'rewindsafe.grant_scope', outcome: 'allow', decisive: false }) }),
    ])
    expect(pendingGate(firstProposal(view), view)).toBe('domain')
  })

  it('waits at the first gate when nothing has been recorded yet', () => {
    const view = buildRunView([event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'inspect_snapshot' } })])
    expect(pendingGate(firstProposal(view), view)).toBe('armoriq')
  })

  it('does not treat a shadow pass as a real pass', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'inspect_snapshot' } }),
      event(2, 'decision', { proposal_id: 'prop-1', decision: decision({ layer: 'armoriq', source: 'armoriq.backend.enforce', outcome: 'allow', shadow: true, decisive: false }) }),
    ])
    expect(pendingGate(firstProposal(view), view)).toBe('armoriq')
  })

  it('has no pending gate for a request that was stopped', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'restore_access_grant' } }),
      event(2, 'decision', { proposal_id: 'prop-1', decision: decision() }),
    ])
    expect(pendingGate(firstProposal(view), view)).toBeUndefined()
  })
})

/* ─── Gate labels ─── */

describe('gateResult', () => {
  it('reads every gate as Waiting when no request is selected', () => {
    const view = buildRunView([])
    expect(gateResult('grant', undefined, cardCtx(view))).toEqual({ label: 'Waiting' })
  })

  it('shows the stopping gate with its outcome, and the gates after it as not reached', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'restore_access_grant' } }),
      event(2, 'decision', { proposal_id: 'prop-1', decision: decision() }),
    ])
    const ctx = cardCtx(view)
    const p = firstProposal(view)
    expect(gateResult('grant', p, ctx).label).toBe('Blocked')
    expect(gateResult('domain', p, ctx).label).toBe('Not reached')
    expect(gateResult('postgres', p, ctx).label).toBe('Not reached')
  })

  it('infers that an earlier gate with no recorded decision passed, because admission is sequential', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'restore_access_grant' } }),
      event(2, 'decision', { proposal_id: 'prop-1', decision: decision() }),
    ])
    expect(gateResult('armoriq', firstProposal(view), cardCtx(view))).toEqual({ label: 'Passed', inferred: true })
  })

  it('reads the gate being checked as Checking, and later gates as not reached yet', () => {
    const view = buildRunView([event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'inspect_snapshot' } })])
    const ctx = cardCtx(view)
    const p = firstProposal(view)
    expect(gateResult('armoriq', p, ctx)).toEqual({ label: 'Checking', pending: true })
    expect(gateResult('grant', p, ctx).label).toBe('Not reached yet')
  })

  it('says a change is waiting for a second person while its approval is pending', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'apply_repair_manifest' } }),
      event(2, 'approval.requested', {
        proposal_id: 'prop-1',
        data: { approval: { approval_id: 'appr-1', proposal_id: 'prop-1', status: 'pending', decided_by: null } },
      }),
    ])
    expect(gateResult('approval', firstProposal(view), cardCtx(view)).label).toBe('Waiting for a second person')
  })

  it('names the reviewer who approved a change that then ran', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'apply_repair_manifest' } }),
      event(2, 'approval.requested', {
        proposal_id: 'prop-1',
        data: { approval: { approval_id: 'appr-1', proposal_id: 'prop-1', status: 'pending', decided_by: null } },
      }),
      event(3, 'approval.resolved', {
        proposal_id: 'prop-1',
        data: { approval: { approval_id: 'appr-1', proposal_id: 'prop-1', status: 'approved', decided_by: 'rev-1' } },
      }),
      event(4, 'tool.result', { proposal_id: 'prop-1', data: { summary: 'Applied' } }),
    ])
    expect(gateResult('approval', firstProposal(view), cardCtx(view)).label).toBe('Approved by Priya Shah')
  })

  // A timed-out approval is not a rejection: the reviewer never decided, so the gate reads "Timed out".
  it('does not label a timed-out approval as a rejection', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'apply_repair_manifest' } }),
      event(2, 'approval.requested', {
        proposal_id: 'prop-1',
        data: { approval: { approval_id: 'appr-1', proposal_id: 'prop-1', status: 'pending', decided_by: null } },
      }),
      event(3, 'approval.resolved', {
        proposal_id: 'prop-1',
        data: { approval: { approval_id: 'appr-1', proposal_id: 'prop-1', status: 'timed_out', decided_by: null } },
      }),
    ])
    expect(gateResult('approval', firstProposal(view), cardCtx(view)).label).not.toBe('Rejected')
  })

  it('shows the database as Committed for a repair with a matching receipt', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'apply_repair_manifest', arguments: { manifest_id: 'man-1' } } }),
      event(2, 'execution.committed', { proposal_id: 'prop-1', data: { receipt: receipt() } }),
    ])
    expect(gateResult('postgres', firstProposal(view), cardCtx(view)).label).toBe('Committed')
  })

  it('says a read-only step that was admitted did not involve the database', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'inspect_snapshot' } }),
      event(2, 'tool.result', { proposal_id: 'prop-1', data: { summary: 'Read' } }),
    ])
    expect(gateResult('postgres', firstProposal(view), cardCtx(view)).label).toBe('Not involved')
  })

  it('shows a stale repair as rejected before any write at the database', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'apply_repair_manifest', arguments: { manifest_id: 'man-1' } } }),
      event(2, 'execution.rejected', { proposal_id: 'prop-1', detail: 'Preconditions changed', data: { manifest_id: 'man-1' } }),
    ])
    expect(gateResult('postgres', firstProposal(view), cardCtx(view)).label).toBe('Rejected before write')
  })
})

/* ─── Whether a committed repair is verified ─── */

describe('recordedVerification', () => {
  it('is true when every check for the repaired orders holds, ignoring other orders’ repair checks', () => {
    const view = buildRunView([
      event(1, 'execution.committed', {
        data: {
          receipt: receipt({
            checks: [
              check({ check_id: 'repair:O-2041', category: 'repair', status: 'repaired' }),
              check({ check_id: 'repair:O-9999', category: 'repair', status: 'pending' }),
              check({ check_id: 'tombstone:O-2041', category: 'tombstone', status: 'preserved' }),
            ],
          }),
        },
      }),
    ])
    expect(recordedVerification(view)).toBe(true)
  })

  it('is false when a repair check for a repaired order is not yet confirmed', () => {
    const view = buildRunView([
      event(1, 'execution.committed', {
        data: {
          receipt: receipt({
            checks: [
              check({ check_id: 'repair:O-2041', category: 'repair', status: 'pending' }),
              check({ check_id: 'tombstone:O-2041', category: 'tombstone', status: 'preserved' }),
            ],
          }),
        },
      }),
    ])
    expect(recordedVerification(view)).toBe(false)
  })

  it('is false when a protected check was violated', () => {
    const view = buildRunView([
      event(1, 'execution.committed', {
        data: {
          receipt: receipt({
            checks: [
              check({ check_id: 'repair:O-2041', category: 'repair', status: 'repaired' }),
              check({ check_id: 'tombstone:O-2041', category: 'tombstone', status: 'violated' }),
            ],
          }),
        },
      }),
    ])
    expect(recordedVerification(view)).toBe(false)
  })

  it('is false when no commit was recorded', () => {
    expect(recordedVerification(buildRunView([]))).toBe(false)
  })
})

/* ─── Outcome headline ─── */

describe('terminalLabel', () => {
  it.each<[RunStatus | undefined, boolean, string]>([
    ['partially_succeeded', false, 'Partly repaired'],
    ['failed', true, 'Failed'],
    ['cancelled', false, 'Cancelled'],
    ['blocked', true, 'Stopped after a repair'],
    ['blocked', false, 'Stopped before any repair'],
    ['succeeded', true, 'Repaired'],
    ['succeeded', false, 'Finished without a recorded repair'],
    [undefined, false, 'Finished without a recorded repair'],
  ])('labels status %s (repaired: %s) as "%s"', (status, repaired, label) => {
    expect(terminalLabel(status, repaired)).toBe(label)
  })
})
