import { describe, expect, it } from 'vitest'
import {
  formatClock,
  formatCountdown,
  formatDate,
  formatDateTime,
  formatDollars,
  formatDuration,
  formatMoney,
  formatShortDate,
  pluralize,
  relativeTime,
  titleCase,
  truncateDigest,
} from './format'

const NOW = Date.parse('2026-10-14T12:00:00Z')
const at = (offsetMs: number): string => new Date(NOW + offsetMs).toISOString()

describe('empty values', () => {
  it('renders null and undefined as "empty" in money, date, duration and digest formatters', () => {
    expect(formatMoney(null)).toBe('empty')
    expect(formatMoney(undefined)).toBe('empty')
    expect(formatDateTime(null)).toBe('empty')
    expect(formatDate(undefined)).toBe('empty')
    expect(formatShortDate(null)).toBe('empty')
    expect(relativeTime(null, NOW)).toBe('empty')
    expect(formatDuration(null)).toBe('empty')
    expect(formatDuration(undefined)).toBe('empty')
    expect(truncateDigest(null)).toBe('empty')
  })

  it('renders an unparseable date as "empty" rather than "Invalid Date"', () => {
    expect(formatDate('not a date')).toBe('empty')
    expect(formatDateTime('2026-13-45T99:99:99Z')).toBe('empty')
  })

  // The clock formatter follows the same EMPTY_TEXT contract as the other date formatters; call sites omit the phrase instead.
  it('renders a null clock value as "empty", like the other date formatters', () => {
    expect(formatClock(null)).toBe('empty')
  })
})

describe('money', () => {
  it('formats integer cents as US dollars', () => {
    expect(formatMoney(124000)).toBe('$1,240.00')
    expect(formatMoney(5)).toBe('$0.05')
    expect(formatMoney(0)).toBe('$0.00')
  })

  it('shows a negative amount with a leading minus sign', () => {
    expect(formatMoney(-500)).toBe('-$5.00')
  })

  it('uses the currency code it is given', () => {
    expect(formatMoney(124000, 'EUR')).toBe('€1,240.00')
  })

  it('treats NaN as empty', () => {
    expect(formatMoney(Number.NaN)).toBe('empty')
  })

  it('formats whole-dollar amounts without cents', () => {
    expect(formatDollars(500000)).toBe('$5,000')
    expect(formatDollars(124000)).toBe('$1,240')
    expect(formatDollars(-250000)).toBe('-$2,500')
  })
})

describe('dates', () => {
  it('shows a timestamp as UTC so everyone reads the same incident clock', () => {
    expect(formatDateTime('2026-10-06T09:12:00Z')).toBe('Oct 6, 09:12 UTC')
  })

  it('converts a timestamp with an offset into UTC', () => {
    expect(formatDateTime('2026-10-06T23:30:00-05:00')).toBe('Oct 7, 04:30 UTC')
  })

  it('shows midnight as 00 and not 24', () => {
    expect(formatDateTime(new Date('2026-10-06T00:05:00Z'))).toBe('Oct 6, 00:05 UTC')
  })

  it('formats a date, a short date and a clock time', () => {
    expect(formatDate('2026-10-06T09:12:00Z')).toBe('Oct 6, 2026')
    expect(formatShortDate('2026-10-06T09:12:00Z')).toBe('Oct 6')
    expect(formatClock('2026-10-06T09:12:05Z')).toBe('09:12:05')
  })
})

describe('relativeTime', () => {
  it('says "just now" for the present and for a few seconds in the past', () => {
    expect(relativeTime(at(0), NOW)).toBe('just now')
    expect(relativeTime(at(-10_000), NOW)).toBe('just now')
  })

  it('says "in a few seconds" for a few seconds in the future', () => {
    expect(relativeTime(at(10_000), NOW)).toBe('in a few seconds')
  })

  it('counts minutes and hours in both directions', () => {
    expect(relativeTime(at(-5 * 60_000), NOW)).toBe('5 minutes ago')
    expect(relativeTime(at(2 * 3_600_000), NOW)).toBe('in 2 hours')
  })

  it('reads one day back as yesterday and several days back by number', () => {
    expect(relativeTime(at(-86_400_000), NOW)).toBe('yesterday')
    expect(relativeTime(at(-3 * 86_400_000), NOW)).toBe('3 days ago')
  })

  it('falls back to an absolute date beyond thirty days', () => {
    expect(relativeTime(at(-40 * 86_400_000), NOW)).toBe('Sep 4, 2026')
  })
})

describe('durations and countdowns', () => {
  it('shows sub-second durations in milliseconds and longer ones in seconds', () => {
    expect(formatDuration(480)).toBe('480 ms')
    expect(formatDuration(1500)).toBe('1.5 s')
  })

  it('shows minutes and seconds for long durations', () => {
    expect(formatDuration(125_000)).toBe('2 min 5 s')
  })

  // Seconds are rounded before the minute is taken, so 119.5 s reads as "2 min 0 s", not "1 min 60 s".
  it('carries rounded seconds into the minute, so 119.5 s reads as 2 min 0 s', () => {
    expect(formatDuration(119_500)).toBe('2 min 0 s')
  })

  it('formats a countdown as minutes and zero-padded seconds', () => {
    expect(formatCountdown(1_694_000)).toBe('28:14')
    expect(formatCountdown(61_000)).toBe('1:01')
    expect(formatCountdown(0)).toBe('0:00')
  })

  it('prefixes an overdue countdown with a minus sign', () => {
    expect(formatCountdown(-12_000)).toBe('-0:12')
  })
})

describe('truncateDigest', () => {
  it('keeps the algorithm prefix and shortens the hex value with an ellipsis', () => {
    expect(truncateDigest('sha256:3f9c1a2b4d5e6f70aabbccdd11223344ab12')).toBe('sha256:3f9c1a2b…ab12')
  })

  it('returns a short digest unchanged', () => {
    expect(truncateDigest('sha256:abc123')).toBe('sha256:abc123')
  })

  it('truncates a digest that has no algorithm prefix', () => {
    expect(truncateDigest('0123456789abcdef0123')).toBe('01234567…0123')
  })

  it('honours custom head and tail lengths', () => {
    expect(truncateDigest('sha256:0123456789abcdef', 4, 2)).toBe('sha256:0123…ef')
  })
})

describe('text helpers', () => {
  it('turns machine slugs into sentence-case words', () => {
    expect(titleCase('order_status')).toBe('Order status')
    expect(titleCase('total-cents.v2')).toBe('Total cents v2')
    expect(titleCase('  spaced   out ')).toBe('Spaced out')
    expect(titleCase('')).toBe('')
  })

  it('pluralises by count, using an explicit plural when given', () => {
    expect(pluralize(1, 'order')).toBe('1 order')
    expect(pluralize(0, 'order')).toBe('0 orders')
    expect(pluralize(2, 'child', 'children')).toBe('2 children')
  })
})
