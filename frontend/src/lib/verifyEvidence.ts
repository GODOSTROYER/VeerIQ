/**
 * Verifies a sealed VeerIQ evidence file entirely in the browser (WebCrypto), with the same rules as
 * scripts/veeriq_verify.py: the payload digest, the hash chain over every event, and the Ed25519
 * signature over the signed statement. Nothing is sent to the server.
 *
 * Digests are SHA-256 over canonical JSON (sorted keys, compact separators, non-ASCII kept), exactly as
 * rewindsafe/runtime/canonical.py writes it. Numbers keep the text they were written with: JavaScript
 * would print the float 1.0 as "1" and change the digest, so the file is parsed with a small reader that
 * stores every number as its original token.
 */

class NumberToken {
  constructor(readonly text: string) {}
}

type Json = null | boolean | string | NumberToken | Json[] | { [key: string]: Json }

/** JSON reader that keeps number tokens verbatim. */
export function parseEvidence(text: string): Json {
  let i = 0
  const space = () => {
    while (i < text.length && ' \t\n\r'.includes(text[i])) i++
  }
  const readString = (): string => {
    const start = i
    i++
    while (text[i] !== '"') {
      if (text[i] === '\\') i++
      i++
      if (i >= text.length) throw new SyntaxError('Unterminated string')
    }
    i++
    return JSON.parse(text.slice(start, i)) as string
  }
  const readValue = (): Json => {
    space()
    const ch = text[i]
    if (ch === '{') {
      i++
      const obj: { [key: string]: Json } = {}
      space()
      if (text[i] === '}') {
        i++
        return obj
      }
      for (;;) {
        space()
        const key = readString()
        space()
        if (text[i++] !== ':') throw new SyntaxError('Expected ":"')
        obj[key] = readValue()
        space()
        const next = text[i++]
        if (next === '}') return obj
        if (next !== ',') throw new SyntaxError('Expected "," or "}"')
      }
    }
    if (ch === '[') {
      i++
      const arr: Json[] = []
      space()
      if (text[i] === ']') {
        i++
        return arr
      }
      for (;;) {
        arr.push(readValue())
        space()
        const next = text[i++]
        if (next === ']') return arr
        if (next !== ',') throw new SyntaxError('Expected "," or "]"')
      }
    }
    if (ch === '"') return readString()
    if (text.startsWith('true', i)) {
      i += 4
      return true
    }
    if (text.startsWith('false', i)) {
      i += 5
      return false
    }
    if (text.startsWith('null', i)) {
      i += 4
      return null
    }
    const m = /^-?\d+(\.\d+)?([eE][+-]?\d+)?/.exec(text.slice(i, i + 64))
    if (!m) throw new SyntaxError(`Unexpected character at ${i}`)
    i += m[0].length
    return new NumberToken(m[0])
  }
  const value = readValue()
  space()
  if (i !== text.length) throw new SyntaxError('Trailing data')
  return value
}

function canonical(value: Json): string {
  if (value instanceof NumberToken) return value.text
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  const keys = Object.keys(value).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`
}

const encoder = new TextEncoder()

async function sha256(value: Json): Promise<string> {
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(canonical(value))))
  return `sha256:${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`
}

function base64Bytes(value: string): Uint8Array {
  const raw = atob(value)
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

function field(obj: Json, key: string): Json {
  if (obj && typeof obj === 'object' && !Array.isArray(obj) && !(obj instanceof NumberToken)) return obj[key] ?? null
  return null
}

export interface EvidenceCheck {
  /** All three checks passed. */
  valid: boolean
  payloadDigest: boolean
  eventChain: boolean
  signature: boolean
  /** The digest recomputed here, to show next to the one in the file. */
  computedDigest: string
  recordedDigest: string
  events: number
  runId: string
  keyFingerprint: string
  error?: string
}

/** Verify a sealed evidence file's text. */
export async function verifyEvidence(text: string): Promise<EvidenceCheck> {
  const empty: EvidenceCheck = {
    valid: false,
    payloadDigest: false,
    eventChain: false,
    signature: false,
    computedDigest: '',
    recordedDigest: '',
    events: 0,
    runId: '',
    keyFingerprint: '',
  }
  try {
    return await verifyParsed(parseEvidence(text))
  } catch (err) {
    return { ...empty, error: err instanceof Error ? err.message : String(err) }
  }
}

export async function verifyParsed(envelope: Json): Promise<EvidenceCheck> {
  const payload = field(envelope, 'payload')
  const signature = field(envelope, 'signature')
  const statement = field(signature, 'statement')
  const events = field(payload, 'events')
  const chain = field(envelope, 'event_chain')
  if (!Array.isArray(events) || !Array.isArray(chain)) throw new Error('Not a sealed evidence file')

  const computedDigest = await sha256(payload)
  const recordedDigest = String(field(envelope, 'payload_digest') ?? '')
  const payloadDigest = computedDigest === recordedDigest && computedDigest === field(statement, 'payload_digest')

  let previous = `sha256:${'0'.repeat(64)}`
  let eventChain = chain.length === events.length
  for (let k = 0; k < events.length && eventChain; k++) {
    const node: { [key: string]: Json } = { seq: field(events[k], 'seq'), event_digest: await sha256(events[k]), previous }
    node.digest = await sha256(node)
    eventChain = node.digest === field(chain[k], 'digest')
    previous = node.digest as string
  }
  eventChain = eventChain && field(statement, 'event_chain_head') === (events.length ? previous : `sha256:${'0'.repeat(64)}`)

  const key = await crypto.subtle.importKey('raw', base64Bytes(String(field(signature, 'public_key'))), { name: 'Ed25519' }, false, ['verify'])
  const sigOk = await crypto.subtle.verify(
    'Ed25519',
    key,
    base64Bytes(String(field(signature, 'signature'))),
    encoder.encode(canonical(statement)),
  )
  return {
    valid: payloadDigest && eventChain && sigOk,
    payloadDigest,
    eventChain,
    signature: sigOk,
    computedDigest,
    recordedDigest,
    events: events.length,
    runId: String(field(field(payload, 'run'), 'run_id') ?? ''),
    keyFingerprint: String(field(signature, 'key_fingerprint') ?? ''),
  }
}

/**
 * The "change one number" test: returns a copy of the file text with one repaired amount raised by one
 * cent (the first total_cents in the payload), so the judge can watch verification fail.
 */
export function tamperOneNumber(text: string): { text: string; changed: string } {
  const m = /"total_cents":\s*(\d+)/.exec(text)
  if (!m || m.index === undefined) return { text: `${text.slice(0, -1)} `, changed: 'one character' }
  const before = m[1]
  const after = String(Number(before) + 1)
  const at = m.index + m[0].length - before.length
  return { text: text.slice(0, at) + after + text.slice(at + before.length), changed: `total_cents ${before} → ${after}` }
}
