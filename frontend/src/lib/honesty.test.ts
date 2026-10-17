import { describe, expect, it } from 'vitest'
import { describeRunOutcome, livePlannerNote, plannerBadge } from './honesty'

describe('describeRunOutcome', () => {
  it('commits', () => {
    expect(describeRunOutcome({ run: { status: 'succeeded' } }).kind).toBe('committed')
  })
  it('rejected by approver with zero commits says no writes', () => {
    const o = describeRunOutcome({ run: { status: 'blocked' }, approvals: [{ status: 'rejected' }], commits: 0, receipts: [] })
    expect(o.kind).toBe('rejected')
    expect(o.title).toContain('No writes were made')
  })
  it('failed with a commit never says no writes', () => {
    const o = describeRunOutcome({ run: { status: 'failed' }, receipts: [{ result: 'committed' }] })
    expect(o.kind).toBe('failed')
    expect(o.title).not.toMatch(/No writes/)
    expect(o.title).toContain('1 commit')
  })
  it('does not claim no writes when commit data is absent', () => {
    const o = describeRunOutcome({ run: { status: 'cancelled' } })
    expect(o.kind).toBe('cancelled')
    expect(o.title).not.toMatch(/No writes/)
  })
  it('partial and unknown are distinct', () => {
    expect(describeRunOutcome({ run: { status: 'partially_succeeded' }, commits: 2 }).kind).toBe('partial')
    expect(describeRunOutcome({ run: { status: 'executing' } }).kind).toBe('unknown')
  })
  it('blocked by a gate is not called rejected', () => {
    expect(describeRunOutcome({ run: { status: 'blocked' }, commits: 0 }).kind).toBe('blocked')
  })
})

describe('livePlannerNote', () => {
  it('labels a scripted planner honestly', () => {
    const t = livePlannerNote({ kind: 'scripted', name: 'scripted' })
    expect(t).toContain('Scripted planner')
    expect(t).not.toMatch(/real model/i)
  })
  it('names a live model', () => {
    expect(livePlannerNote({ kind: 'llm', name: 'gpt-oss-120b', provider: 'groq' })).toContain('Live model: groq gpt-oss-120b')
  })
  it('badge follows kind', () => {
    expect(plannerBadge('scripted')).toBe('scripted planner')
    expect(plannerBadge('llm')).toBe('live model')
  })
})
