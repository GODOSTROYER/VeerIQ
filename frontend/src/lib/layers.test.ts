import { describe, expect, it } from 'vitest'
import type { Decision, DecisionSource, Layer } from '@/api/types'
import {
  DECISION_SOURCES,
  DEFENSE_LAYERS,
  LAYERS,
  decisionHeadline,
  isSimulatedEnforcement,
  layerOfSource,
  sourceLabel,
} from './layers'

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    decision_id: 'dec-1',
    run_id: 'run-1',
    proposal_id: 'prop-1',
    layer: 'armoriq',
    source: 'armoriq.sdk.plan_binding',
    outcome: 'block',
    decisive: true,
    shadow: false,
    simulated: false,
    reason: 'tool-not-in-plan',
    invariant: null,
    latency_ms: null,
    sponsor: null,
    evidence: {},
    created_at: '2026-10-06T09:12:00Z',
    ...overrides,
  }
}

describe('isSimulatedEnforcement', () => {
  it('reports live only when the mode, the plan and every decision all say live', () => {
    expect(
      isSimulatedEnforcement({
        enforcement_mode: 'live',
        plan: { mode: 'live', simulated: false },
        decisions: [{ simulated: false }, { simulated: false }],
      }),
    ).toBe(false)
  })

  it('treats a live-mode run as simulated when its signed plan is simulated', () => {
    expect(isSimulatedEnforcement({ enforcement_mode: 'live', plan: { mode: 'live', simulated: true } })).toBe(true)
  })

  it('treats a plan that is not in live mode as simulated, even if its flag says not simulated', () => {
    expect(isSimulatedEnforcement({ enforcement_mode: 'live', plan: { mode: 'offline', simulated: false } })).toBe(true)
  })

  it('treats an offline run as simulated even when its plan and decisions look live', () => {
    expect(
      isSimulatedEnforcement({
        enforcement_mode: 'offline',
        plan: { mode: 'live', simulated: false },
        decisions: [{ simulated: false }],
      }),
    ).toBe(true)
  })

  it('makes the whole run simulated when a single decision is simulated', () => {
    expect(
      isSimulatedEnforcement({
        enforcement_mode: 'live',
        plan: { mode: 'live', simulated: false },
        decisions: [{ simulated: false }, { simulated: true }],
      }),
    ).toBe(true)
  })

  it('counts a decision whose simulated flag is missing or null as simulated', () => {
    expect(isSimulatedEnforcement({ enforcement_mode: 'live', decisions: [{}] })).toBe(true)
    expect(isSimulatedEnforcement({ enforcement_mode: 'live', decisions: [{ simulated: null }] })).toBe(true)
  })

  it('counts a plan whose simulated flag is missing as simulated', () => {
    expect(isSimulatedEnforcement({ enforcement_mode: 'live', plan: { mode: 'live' } })).toBe(true)
  })

  it('counts a missing, null or unrecognised enforcement mode as simulated', () => {
    expect(isSimulatedEnforcement({})).toBe(true)
    expect(isSimulatedEnforcement({ enforcement_mode: null })).toBe(true)
    expect(isSimulatedEnforcement({ enforcement_mode: 'staging' })).toBe(true)
  })

  // Absent facts are not evidence of simulation: the plan and decisions fill in while the run proceeds.
  it('does not call a live-mode run with no bound plan and no decisions yet simulated', () => {
    expect(isSimulatedEnforcement({ enforcement_mode: 'live', plan: null, decisions: [] })).toBe(false)
  })
})

describe('decision source labelling', () => {
  it('flags exactly the ArmorIQ sources as ArmorIQ, so no VeerIQ or PostgreSQL decision can carry it', () => {
    for (const [source, meta] of Object.entries(DECISION_SOURCES)) {
      expect(meta.armoriq, source).toBe(meta.layer === 'armoriq')
    }
  })

  it('gives every decision source a layer with display metadata', () => {
    for (const meta of Object.values(DECISION_SOURCES)) {
      expect(LAYERS[meta.layer].label).not.toBe('')
    }
  })

  it.each<[DecisionSource, Layer]>([
    ['armoriq.sdk.plan_binding', 'armoriq'],
    ['armoriq.backend.enforce', 'armoriq'],
    ['armoriq.offline_simulation', 'armoriq'],
    ['rewindsafe.grant_scope', 'grant'],
    ['rewindsafe.domain', 'domain'],
    ['rewindsafe.approval', 'approval'],
    ['rewindsafe.lifecycle', 'runtime'],
    ['postgres.transaction', 'postgres'],
  ])('attributes %s to the %s layer', (source, layer) => {
    expect(layerOfSource(source)).toBe(layer)
  })

  it('attributes an unrecognised source to the runtime, not to a defence layer', () => {
    const unknown: string = 'vendor.new_check'
    expect(layerOfSource(unknown as DecisionSource)).toBe('runtime')
  })

  it('labels the live ArmorIQ signed-plan check as signed plan, not as simulated', () => {
    expect(sourceLabel({ source: 'armoriq.sdk.plan_binding', simulated: false })).toBe('ArmorIQ - signed plan')
  })

  it('labels the offline simulation source as simulated, even when the flag is false', () => {
    expect(sourceLabel({ source: 'armoriq.offline_simulation', simulated: false })).toBe('ArmorIQ (simulated)')
  })

  it('adds the simulated label to any decision flagged simulated, whatever its source', () => {
    expect(sourceLabel({ source: 'armoriq.backend.enforce', simulated: true })).toBe('ArmorIQ - policy (simulated)')
    expect(sourceLabel({ source: 'rewindsafe.domain', simulated: true })).toBe('Domain invariant (simulated)')
  })

  it('never labels a VeerIQ or PostgreSQL decision as ArmorIQ', () => {
    for (const [source, meta] of Object.entries(DECISION_SOURCES)) {
      if (meta.layer === 'armoriq') continue
      expect(sourceLabel({ source: source as DecisionSource, simulated: false }), source).not.toMatch(/ArmorIQ/)
    }
  })

  it('shows an unrecognised source as its raw code', () => {
    const unknown: string = 'vendor.mystery'
    expect(sourceLabel({ source: unknown as DecisionSource, simulated: false })).toBe('vendor.mystery')
  })
})

describe('decisionHeadline', () => {
  it('names the deciding ArmorIQ check for a block', () => {
    expect(decisionHeadline(decision({ source: 'armoriq.backend.enforce', outcome: 'block' }))).toBe(
      'ArmorIQ - policy blocked this action',
    )
  })

  it('describes a shadow decision as what would have happened, not what happened', () => {
    expect(
      decisionHeadline(decision({ source: 'armoriq.backend.enforce', outcome: 'block', shadow: true })),
    ).toBe('ArmorIQ - policy would also have blocked this')
  })

  it('does not describe an enforcement outage as a block', () => {
    const headline = decisionHeadline(decision({ source: 'armoriq.sdk.plan_binding', outcome: 'unavailable' }))
    expect(headline).toContain('could not be checked')
    expect(headline).not.toContain('blocked')
  })

  it('keeps the simulated label in the headline of a simulated decision', () => {
    expect(
      decisionHeadline(decision({ source: 'armoriq.backend.enforce', outcome: 'block', simulated: true })),
    ).toContain('(simulated)')
  })
})

describe('defence layers', () => {
  it('lists only defence tiers, leaving out the runtime plumbing, outermost first', () => {
    expect(DEFENSE_LAYERS).not.toContain('runtime')
    expect(DEFENSE_LAYERS[0]).toBe('armoriq')
    for (const layer of DEFENSE_LAYERS) {
      expect(LAYERS[layer].label).not.toBe('')
    }
  })
})
