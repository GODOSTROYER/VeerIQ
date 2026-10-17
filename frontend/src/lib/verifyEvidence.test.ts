import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { PINNED_OPERATOR_PUBLIC_KEY, parseEvidence, tamperOneNumber, verifyEvidence } from './verifyEvidence'

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

  it('pins the same key as verification/operator-public-key.pem', () => {
    const pem = sample('operator-public-key.pem').replace(/-----[^-]+-----|\s/g, '')
    expect(Buffer.from(pem, 'base64').subarray(-32).toString('base64')).toBe(PINNED_OPERATOR_PUBLIC_KEY)
  })

  it('reports the shipped export as trusted, with a fingerprint computed from the key bytes', async () => {
    const r = await verifyEvidence(sample('valid-live-recovery.json'))
    expect(r).toMatchObject({ valid: true, integrity: true, trust: 'trusted', fingerprintField: true })
    expect(r.verdict).toMatch(/^Verified: signed by VeerIQ's pinned operator key \(fingerprint sha256:/)
    expect(r.keyFingerprint).toBe(r.pinnedFingerprint)
  })

  it('does not call an envelope re-signed with a different key verified', async () => {
    const env = JSON.parse(sample('valid-live-recovery.json'))
    const pair = (await crypto.subtle.generateKey('Ed25519', true, ['sign', 'verify'])) as CryptoKeyPair
    const raw = new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey))
    const sortKeys = (v: unknown): unknown =>
      Array.isArray(v)
        ? v.map(sortKeys)
        : v && typeof v === 'object'
          ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortKeys((v as Record<string, unknown>)[k])]))
          : v
    const body = new TextEncoder().encode(JSON.stringify(sortKeys(env.signature.statement)))
    const sig = new Uint8Array(await crypto.subtle.sign('Ed25519', pair.privateKey, body))
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', raw))
    env.signature.public_key = Buffer.from(raw).toString('base64')
    env.signature.key_fingerprint = `sha256:${Buffer.from(digest).toString('hex')}`
    env.signature.signature = Buffer.from(sig).toString('base64')
    const r = await verifyEvidence(JSON.stringify(env))
    expect(r.integrity).toBe(true)
    expect(r.trust).toBe('untrusted')
    expect(r.valid).toBe(false)
    expect(r.verdict).toBe('Signature valid, but signed by an unknown key — NOT trusted')
  })

  it('reports embedded key only when no key is pinned', async () => {
    const r = await verifyEvidence(sample('valid-live-recovery.json'), null)
    expect(r).toMatchObject({ integrity: true, trust: 'no-pinned-key', valid: false })
    expect(r.verdict).toBe('Embedded key only, signer not verified')
  })

  it('detects an altered key_fingerprint field', async () => {
    const env = JSON.parse(sample('valid-live-recovery.json'))
    env.signature.key_fingerprint = `sha256:${'a'.repeat(64)}`
    const r = await verifyEvidence(JSON.stringify(env))
    expect(r).toMatchObject({ fingerprintField: false, integrity: false, valid: false })
    expect(r.verdict).toMatch(/^Integrity failed/)
  })

  it('fails integrity when the event chain is tampered', async () => {
    const env = JSON.parse(sample('valid-live-recovery.json'))
    env.event_chain[0].digest = `sha256:${'b'.repeat(64)}`
    const r = await verifyEvidence(JSON.stringify(env))
    expect(r).toMatchObject({ eventChain: false, integrity: false, valid: false })
    expect(r.verdict).toMatch(/^Integrity failed/)
  })

  it('rejects files with missing required fields', async () => {
    const env = JSON.parse(sample('valid-live-recovery.json'))
    delete env.signature.public_key
    const r = await verifyEvidence(JSON.stringify(env))
    expect(r.valid).toBe(false)
    expect(r.error).toMatch(/public_key/)
    expect((await verifyEvidence('{}')).valid).toBe(false)
  })
})
