const moneyFormatters = new Map<string, Intl.NumberFormat>()

/** What a null or missing value reads as in copy. Callers that can omit the clause should do so instead. */
export const EMPTY_TEXT = 'empty'

/** Format integer cents as currency, e.g. 124000 -> "$1,240.00". */
export function formatMoney(cents: number | null | undefined, currency = 'USD'): string {
  if (cents === null || cents === undefined || Number.isNaN(cents)) return EMPTY_TEXT
  let f = moneyFormatters.get(currency)
  if (!f) {
    f = new Intl.NumberFormat('en-US', { style: 'currency', currency })
    moneyFormatters.set(currency, f)
  }
  return f.format(cents / 100)
}

/** Whole-dollar variant for compact copy ("$5,000"). */
export function formatDollars(cents: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 0 }).format(cents / 100)
}

const dateTimeFmt = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  hour12: false,
  timeZone: 'UTC',
})
const dateFmt = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
const shortDateFmt = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
const timeFmt = new Intl.DateTimeFormat('en-US', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
  timeZone: 'UTC',
})

function toDate(v: string | Date | null | undefined): Date | null {
  if (!v) return null
  const d = v instanceof Date ? v : new Date(v)
  return Number.isNaN(d.getTime()) ? null : d
}

/** "Oct 6, 09:12 UTC". Data timestamps are shown in UTC so everyone reads the same incident clock. */
export function formatDateTime(v: string | Date | null | undefined): string {
  const d = toDate(v)
  return d ? `${dateTimeFmt.format(d)} UTC` : EMPTY_TEXT
}
export function formatDate(v: string | Date | null | undefined): string {
  const d = toDate(v)
  return d ? dateFmt.format(d) : EMPTY_TEXT
}
export function formatShortDate(v: string | Date | null | undefined): string {
  const d = toDate(v)
  return d ? shortDateFmt.format(d) : EMPTY_TEXT
}
export function formatClock(v: string | Date | null | undefined): string {
  const d = toDate(v)
  return d ? timeFmt.format(d) : EMPTY_TEXT
}
/** True when the value is a real timestamp, so a phrase that shows its time can be kept; otherwise omit the phrase. */
export function hasTime(v: string | Date | null | undefined): boolean {
  return toDate(v) !== null
}

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

/** "3 minutes ago", "in 2 hours". */
export function relativeTime(v: string | Date | null | undefined, now: number = Date.now()): string {
  const d = toDate(v)
  if (!d) return EMPTY_TEXT
  const diff = (d.getTime() - now) / 1000
  const abs = Math.abs(diff)
  if (abs < 45) return diff <= 0 ? 'just now' : 'in a few seconds'
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), 'day')
  return formatDate(d)
}

/** "28:14" countdown or "-0:12" when overdue. */
export function formatCountdown(ms: number): string {
  const neg = ms < 0
  const s = Math.floor(Math.abs(ms) / 1000)
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${neg ? '-' : ''}${m}:${String(r).padStart(2, '0')}`
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return EMPTY_TEXT
  if (ms < 1000) return `${Math.round(ms)} ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)} s`
  // Round the whole duration first, so seconds that round up to 60 carry into the minute.
  const whole = Math.round(s)
  return `${Math.floor(whole / 60)} min ${whole % 60} s`
}

/** "sha256:3f9c1a2b...ab12" for display; the full value stays available via copy. */
export function truncateDigest(d: string | null | undefined, head = 8, tail = 4): string {
  if (!d) return EMPTY_TEXT
  const [prefix, hex] = d.includes(':') ? [d.slice(0, d.indexOf(':') + 1), d.slice(d.indexOf(':') + 1)] : ['', d]
  if (hex.length <= head + tail + 1) return d
  return `${prefix}${hex.slice(0, head)}\u2026${hex.slice(-tail)}`
}

export function titleCase(slug: string): string {
  return slug
    .replace(/[._-]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
    .replace(/^\w/, (c) => c.toUpperCase())
}

export function pluralize(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}
