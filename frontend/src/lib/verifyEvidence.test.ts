import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { parseEvidence, tamperOneNumber, verifyEvidence } from './verifyEvidence'

const sample = (name: string) => readFileSync(resolve(__dirname, '../../public/verification', name), 'utf8')

describe('verifyEvidence (in-browser verifier, same rules as veeriq_verify.py)', () => {
  it('accepts the signed live recovery export', async () => {
    const result = await verifyEvidence(sample('valid-live-recovery.json'))
    expect(result).toMatchObject({ valid: true, payloadDigest: true, eventChain: true, signature: true })
    expect(result.computedDigest).toBe(result.recordedDigest)
    expect(result.events).toBeGreaterThan(0)
  })

  it('accepts the audit-linked export too', async () => {
    expect((await verifyEvidence(sample('audit-linked-scripted-live-sealed.json'))).valid).toBe(true)
  })

  it('rejects the shipped tampered copy', async () => {
    const result = await verifyEvidence(sample('tampered-live-recovery.json'))
    expect(result.valid).toBe(false)
    expect(result.payloadDigest).toBe(false)
  })

  it('rejects a one-cent change', async () => {
    const tampered = tamperOneNumber(sample('valid-live-recovery.json'))
    expect(tampered.changed).toMatch(/total_cents \d+ → \d+/)
    expect((await verifyEvidence(tampered.text)).valid).toBe(false)
  })

  it('keeps number tokens verbatim (1.0 must not become 1)', () => {
    const parsed = parseEvidence('{"a":1.0,"b":[2.50,1e-05]}') as Record<string, unknown>
    expect(JSON.stringify(parsed)).toContain('"text":"1.0"')
  })

  it('reports malformed input as invalid instead of throwing', async () => {
    const result = await verifyEvidence('{"payload": ')
    expect(result.valid).toBe(false)
    expect(result.error).toBeTruthy()
  })
})
