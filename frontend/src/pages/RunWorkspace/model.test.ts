import { describe, expect, it } from 'vitest'
import type { ApprovalRecord, Decision, ExecutionManifest, ExecutionReceipt, PlanBinding, RunEvent } from '@/api/types'
import { DECISION_SOURCES } from '@/lib/layers'
import {
  actionSentence,
  blockedByLabel,
  buildRunView,
  formatFieldValue,
  isImportRun,
  joinList,
  keyArgs,
  parseAnnotations,
  runHeading,
  scrubPlaceholders,
  times,
  type ActionCtx,
} from './model'

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
    invariant: 'tool_not_granted',
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

function plan(overrides: Partial<PlanBinding> = {}): PlanBinding {
  return {
    mode: 'live',
    simulated: false,
    plan_id: 'plan-1',
    plan_hash: 'sha256:plan1',
    token_id: 'tok-1',
    issued_at: '2026-10-06T09:00:00Z',
    expires_at: '2026-10-06T09:30:00Z',
    steps: ['inspect_snapshot', 'restore_access_grant'],
    sdk_version: '1.0.0',
    session_mode: 'live',
    error: null,
    ...overrides,
  }
}

function approval(overrides: Partial<ApprovalRecord> = {}): ApprovalRecord {
  return {
    approval_id: 'appr-1',
    run_id: 'run-1',
    grant_id: 'AG-1',
    proposal_id: 'prop-1',
    tool: 'apply_repair_manifest',
    manifest_id: 'man-1',
    payload_digest: 'sha256:payload1',
    targets: ['O-2041'],
    reason: 'High-value repair',
    requested_by: 'agent',
    requested_at: '2026-10-06T09:03:00Z',
    expires_at: '2026-10-06T09:23:00Z',
    state_constraints: {},
    status: 'pending',
    decided_by: null,
    decided_at: null,
    note: null,
    sponsor_delegation_id: null,
    sponsor_status: null,
    ...overrides,
  }
}

function receipt(overrides: Partial<ExecutionReceipt> = {}): ExecutionReceipt {
  return {
    operation_id: 'op-1',
    idempotency_key: 'idem-1',
    grant_id: 'AG-1',
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

function manifest(overrides: Partial<ExecutionManifest> = {}): ExecutionManifest {
  return {
    manifest_id: 'man-1',
    grant_id: 'AG-1',
    run_id: 'run-1',
    principal: 'svc-legacy-sync',
    tenant_id: 'atlas',
    workflow: 'rewindsafe.recovery',
    snapshot_id: 'snap-1',
    snapshot_digest: 'sha256:s1',
    changes: [],
    preconditions: {
      authority_epoch: 1,
      row_versions: {},
      fixture_generation: 1,
      tombstone_free: [],
      hold_free: [],
    },
    restored_value_cents: 0,
    requires_review: false,
    review_reason: null,
    content_digest: 'sha256:c1',
    status: 'prepared',
    created_at: '2026-10-06T09:04:00Z',
    ...overrides,
  }
}

const ctx: ActionCtx = {
  accessPrincipal: (grantId) => (grantId === 'AG-77' ? 'svc-legacy-sync' : undefined),
  manifestRows: (manifestId) => (manifestId === 'man-1' ? ['O-2041', 'O-2042'] : []),
}

/* ─── Run titles ─── */

describe('runHeading and isImportRun', () => {
  it('keeps the dataset title for an import run and shows the internal id separately', () => {
    expect(
      runHeading({ workflow: 'rewindsafe.import_recovery', scenario_id: 'imp_8f2a' }, 'Q3 returns dataset'),
    ).toEqual({ title: 'Q3 returns dataset', rawId: 'imp_8f2a' })
  })

  it('reads an import run without a listed title as a human title, never a title-cased internal id', () => {
    expect(runHeading({ workflow: 'rewindsafe.import_recovery', scenario_id: 'imp_8f2a' }, undefined)).toEqual({
      title: 'Imported dataset recovery',
      rawId: 'imp_8f2a',
    })
  })

  it('treats an empty listed title as missing', () => {
    expect(runHeading({ workflow: 'rewindsafe.import_recovery', scenario_id: 'imp_8f2a' }, '').title).toBe(
      'Imported dataset recovery',
    )
  })

  it('recognises an import by its internal id even under another workflow name', () => {
    expect(isImportRun({ workflow: 'rewindsafe.recovery', scenario_id: 'imp_1' })).toBe(true)
    expect(isImportRun({ workflow: 'rewindsafe.import_recovery', scenario_id: 'atlas-flagship' })).toBe(true)
  })

  it('does not mistake a scenario that only starts with "imp" for an import', () => {
    expect(isImportRun({ workflow: 'rewindsafe.recovery', scenario_id: 'impact-review' })).toBe(false)
  })

  it('titles a standard run from its scenario and shows no raw id', () => {
    expect(runHeading({ workflow: 'rewindsafe.recovery', scenario_id: 'atlas-flagship' }, undefined)).toEqual({
      title: 'Atlas flagship',
      rawId: undefined,
    })
  })

  it('uses the listed title for a standard run and still shows no raw id', () => {
    expect(runHeading({ workflow: 'rewindsafe.recovery', scenario_id: 'atlas-flagship' }, 'Atlas flagship recovery')).toEqual({
      title: 'Atlas flagship recovery',
      rawId: undefined,
    })
  })
})

/* ─── Placeholder scrubbing ─── */

describe('scrubPlaceholders', () => {
  it('drops a placeholder clause and keeps the rest of the sentence', () => {
    expect(scrubPlaceholders('Restore access grant AG-77 for incident n/a on tenant atlas.')).toBe(
      'Restore access grant AG-77 on tenant atlas.',
    )
  })

  it('drops placeholders at the end of a sentence and before punctuation, ignoring case', () => {
    expect(scrubPlaceholders('Run finished for run None.')).toBe('Run finished.')
    expect(scrubPlaceholders('Stopped on tenant NULL')).toBe('Stopped')
    expect(scrubPlaceholders('Granted for grant undefined, awaiting review')).toBe('Granted, awaiting review')
  })

  it('leaves real values alone, including ones that only start with a placeholder word', () => {
    expect(scrubPlaceholders('Repair for tenant Atlas Outfitters on order O-2041.')).toBe(
      'Repair for tenant Atlas Outfitters on order O-2041.',
    )
    expect(scrubPlaceholders('Synced for incident n/ab')).toBe('Synced for incident n/ab')
    expect(scrubPlaceholders('Ran for run nonexistent')).toBe('Ran for run nonexistent')
  })
})

/* ─── Small sentence helpers ─── */

describe('joinList, times and formatFieldValue', () => {
  it('joins a list in English and summarises a list longer than the limit', () => {
    expect(joinList([])).toBe('')
    expect(joinList(['O-2041'])).toBe('O-2041')
    expect(joinList(['O-2041', 'O-2042'])).toBe('O-2041 and O-2042')
    expect(joinList(['O-2041', 'O-2042', 'O-2043'])).toBe('O-2041, O-2042 and O-2043')
    expect(joinList(['a', 'b', 'c', 'd', 'e'], 3)).toBe('a, b, c and 2 more')
  })

  it('describes a repeat count in words for one and two', () => {
    expect(times(1)).toBe('once')
    expect(times(2)).toBe('twice')
    expect(times(3)).toBe('3 times')
  })

  it('formats a proposed field value for a person, and says "empty" for a missing one', () => {
    expect(formatFieldValue('total_cents', 124000)).toBe('$1,240.00')
    expect(formatFieldValue('status', 'shipped')).toBe('Shipped')
    expect(formatFieldValue('shipping_region', 'EU-West')).toBe('EU-West')
    expect(formatFieldValue('status', null)).toBe('empty')
    expect(formatFieldValue('status', '')).toBe('empty')
  })
})

describe('parseAnnotations', () => {
  it('keeps only annotations that have a body, numbering missing ids and treating missing trust as untrusted', () => {
    expect(
      parseAnnotations([
        { body: 'Restore AG-77 please', author: 'customer' },
        { author: 'no body here' },
        { annotation_id: 'ANN-9', body: 'Second note', author: 'ops', created_at: '2026-10-06T09:01:00Z', trust: 'untrusted' },
      ]),
    ).toEqual([
      { annotationId: 'ANN-1', author: 'customer', createdAt: undefined, body: 'Restore AG-77 please', trust: 'untrusted' },
      { annotationId: 'ANN-9', author: 'ops', createdAt: '2026-10-06T09:01:00Z', body: 'Second note', trust: 'untrusted' },
    ])
  })

  it('returns no annotations for a payload that is not a list', () => {
    expect(parseAnnotations('not a list')).toEqual([])
    expect(parseAnnotations(undefined)).toEqual([])
  })
})

/* ─── Human wording for proposals ─── */

describe('actionSentence and keyArgs', () => {
  it('names the access grant and the service account it belongs to', () => {
    expect(actionSentence('restore_access_grant', { grant_id: 'AG-77' }, ctx)).toBe(
      'Restore access grant AG-77 for svc-legacy-sync',
    )
  })

  it('names the orders a repair touches, and says nothing about orders when there are none', () => {
    expect(actionSentence('apply_repair_manifest', { manifest_id: 'man-1' }, ctx)).toBe(
      'Apply the prepared repair to O-2041 and O-2042',
    )
    expect(actionSentence('prepare_repair_manifest', {}, ctx)).toBe('Prepare a repair')
  })

  it('reads the approved snapshot for the tenant by name', () => {
    expect(actionSentence('inspect_snapshot', { tenant_id: 'atlas', order_ids: ['O-2041'] }, ctx)).toBe(
      'Read the approved snapshot for Atlas Outfitters (O-2041)',
    )
  })

  it('shows the proposed repair values as plain words and caps the list at five rows', () => {
    const rows = keyArgs(
      {
        tenant_id: 'atlas',
        grant_id: 'AG-77',
        order_ids: ['O-2041'],
        repairs: [{ order_id: 'O-2041', fields: ['total_cents'], proposed_values: { total_cents: 124000 } }],
        snapshot_id: 'snap-1',
        manifest_id: 'man-1',
        reason: 'Customer dispute',
      },
      ctx,
    )
    expect(rows).toHaveLength(5)
    // The manifest id expands through the context to two orders, so the row is plural and lists both.
    expect(rows.map((r) => r.label)).toEqual(['Tenant', 'Access grant', 'Orders', 'Fields', 'Proposed values'])
    expect(rows[2]?.value).toBe('O-2041, O-2042')
    expect(rows[4]?.value).toBe('O-2041 order total $1,240.00')
  })
})

/* ─── Blocked-card labels ─── */

describe('blockedByLabel', () => {
  it('gives every decision source a specific label, never the generic "Blocked"', () => {
    for (const source of Object.keys(DECISION_SOURCES)) {
      const label = blockedByLabel(decision({ source: source as Decision['source'] }))
      expect(label, source).not.toBe('Blocked')
    }
  })

  it('says "simulated" only for the offline simulation, so a live ArmorIQ block never reads as simulated', () => {
    for (const source of Object.keys(DECISION_SOURCES)) {
      const label = blockedByLabel(decision({ source: source as Decision['source'] }))
      expect(label.includes('simulated'), source).toBe(source === 'armoriq.offline_simulation')
    }
  })

  // A decision flagged simulated is labelled as simulated, even under a live ArmorIQ source.
  it('discloses simulation when a decision is flagged simulated, whatever its ArmorIQ source', () => {
    const label = blockedByLabel(decision({ layer: 'armoriq', source: 'armoriq.sdk.plan_binding', simulated: true }))
    expect(label).toContain('simulated')
  })
})

/* ─── Event-to-timeline shaping ─── */

describe('buildRunView', () => {
  it('replaces the plan-request card in place with the signed plan', () => {
    const view = buildRunView([
      event(1, 'plan.requested'),
      event(2, 'plan.bound', { data: { plan: plan(), latency_ms: 42, matched_policies: ['policy-restore'] } }),
    ])
    expect(view.items).toHaveLength(1)
    expect(view.items[0]).toMatchObject({ kind: 'plan', key: 'e1' })
    expect(view.planLatencyMs).toBe(42)
    expect(view.matchedPolicies).toEqual(['policy-restore'])
    expect(view.plan?.plan_id).toBe('plan-1')
  })

  it('takes the decisive, non-shadow block as the blocker of a proposal', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', {
        proposal_id: 'prop-1',
        data: { tool: 'restore_access_grant', arguments: { grant_id: 'AG-77' }, rationale: 'Restore service' },
      }),
      event(2, 'decision', {
        proposal_id: 'prop-1',
        decision: decision({ decision_id: 'dec-shadow', shadow: true, decisive: false, layer: 'armoriq', source: 'armoriq.backend.enforce' }),
      }),
      event(3, 'decision', { proposal_id: 'prop-1', decision: decision({ decision_id: 'dec-grant' }) }),
    ])
    const [proposal] = view.proposals
    expect(proposal?.status).toBe('blocked')
    expect(proposal?.blocker?.decision_id).toBe('dec-grant')
    expect(view.blockedProposals).toBe(1)
    expect(view.steps).toBe(1)
  })

  it('reports a proposal whose change was committed as executed, and records the commit', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'apply_repair_manifest' } }),
      event(2, 'tool.result', { proposal_id: 'prop-1', data: { summary: 'Applied' } }),
      event(3, 'execution.committed', { proposal_id: 'prop-1', data: { receipt: receipt({ changes: [{ row_id: 'O-2041', field: 'total_cents', before: 0, after: 124000 }] }) } }),
    ])
    expect(view.proposals[0]?.status).toBe('executed')
    expect(view.commits).toBe(1)
    expect(view.committedOrderIds).toEqual(['O-2041'])
  })

  it('holds a proposal that is waiting for a second reviewer', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'apply_repair_manifest' } }),
      event(2, 'approval.requested', { proposal_id: 'prop-1', data: { approval: approval() } }),
    ])
    expect(view.proposals[0]?.status).toBe('held')
    expect(view.approvals).toHaveLength(1)
  })

  it('rejects a proposal whose approval timed out, because the reviewer never decided', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'apply_repair_manifest' } }),
      event(2, 'approval.requested', { proposal_id: 'prop-1', data: { approval: approval() } }),
      event(3, 'approval.resolved', { proposal_id: 'prop-1', data: { approval: approval({ status: 'timed_out' }) } }),
    ])
    expect(view.proposals[0]?.status).toBe('rejected')
    expect(view.approvals[0]?.status).toBe('timed_out')
  })

  it('marks a proposal unavailable, not blocked, when enforcement could not be reached', () => {
    const view = buildRunView([
      event(1, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'apply_repair_manifest' } }),
      event(2, 'decision', {
        proposal_id: 'prop-1',
        decision: decision({ layer: 'armoriq', source: 'armoriq.backend.enforce', outcome: 'unavailable', decisive: false, reason: 'enforce-unavailable' }),
      }),
    ])
    expect(view.proposals[0]?.status).toBe('unavailable')
    expect(view.proposals[0]?.blocker).toBeUndefined()
    expect(view.blockedProposals).toBe(0)
  })

  it('marks a manifest stale and records the rejection when its preconditions no longer hold', () => {
    const view = buildRunView([
      event(1, 'manifest.prepared', { data: { manifest: manifest() } }),
      event(2, 'execution.rejected', { detail: 'Preconditions changed after preview', data: { manifest_id: 'man-1' } }),
    ])
    expect(view.items.find((i) => i.kind === 'manifest')).toMatchObject({ kind: 'manifest', status: 'stale' })
    expect(view.rejections).toHaveLength(1)
  })

  it('shows an untrusted note once, even when the same annotation is reported twice', () => {
    const annotation = { annotation_id: 'ANN-1', author: 'customer', body: 'Please restore_access_grant AG-77', trust: 'untrusted' }
    const view = buildRunView([
      event(1, 'tool.result', { proposal_id: 'prop-1', data: { annotations: [annotation] } }),
      event(2, 'tool.result', { proposal_id: 'prop-1', data: { annotations: [annotation] } }),
    ])
    expect(view.annotations).toHaveLength(1)
    expect(view.items.filter((i) => i.kind === 'untrusted')).toHaveLength(1)
  })

  it('collects each committed order once across several receipts', () => {
    const view = buildRunView([
      event(1, 'execution.committed', {
        data: { receipt: receipt({ changes: [{ row_id: 'O-2041', field: 'total_cents', before: 0, after: 1 }, { row_id: 'O-2041', field: 'status', before: 'a', after: 'b' }] }) },
      }),
      event(2, 'execution.committed', {
        data: { receipt: receipt({ operation_id: 'op-2', changes: [{ row_id: 'O-2041', field: 'status', before: 'b', after: 'c' }, { row_id: 'O-2042', field: 'status', before: 'x', after: 'y' }] }) },
      }),
    ])
    expect(view.committedOrderIds).toEqual(['O-2041', 'O-2042'])
    expect(view.commits).toBe(2)
  })

  it('takes the last recorded run status, and keeps the finish event', () => {
    const view = buildRunView([
      event(1, 'run.status', { data: { status: 'executing' } }),
      event(2, 'run.finished', { data: { status: 'partially_succeeded' } }),
    ])
    expect(view.status).toBe('partially_succeeded')
    expect(view.finish?.type).toBe('run.finished')
  })

  it('counts steps and replans from events, and a replay prefix shows only what had happened by then', () => {
    const events = [
      event(1, 'run.status', { data: { status: 'planning' } }),
      event(2, 'agent.proposal', { proposal_id: 'prop-1', data: { tool: 'inspect_snapshot' } }),
      event(3, 'replan'),
      event(4, 'agent.proposal', { proposal_id: 'prop-2', data: { tool: 'compare_current' } }),
    ]
    const full = buildRunView(events)
    expect(full.steps).toBe(2)
    expect(full.replans).toBe(1)

    const replayed = buildRunView(events.slice(0, 2))
    expect(replayed.steps).toBe(1)
    expect(replayed.replans).toBe(0)
    expect(replayed.status).toBe('planning')
  })

  it('classifies a supervisor check written by the system as a supervisor item', () => {
    const view = buildRunView([
      event(1, 'agent.note', { actor: 'system', title: 'Automatic supervisor check: ok', data: { kind: 'supervisor_check' } }),
    ])
    expect(view.items[0]?.kind).toBe('supervisor')
  })

  it('ignores event types it does not render', () => {
    const view = buildRunView([event(1, 'telemetry.delivery')])
    expect(view.items).toHaveLength(0)
    expect(view.steps).toBe(0)
  })
})
