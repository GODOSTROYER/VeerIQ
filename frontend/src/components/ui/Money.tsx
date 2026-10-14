import { cn } from '@/lib/cn'
import { formatMoney } from '@/lib/format'

export interface MoneyProps {
  cents: number | null | undefined
  currency?: string
  /** Colour semantic: bad = damaged value, good = repaired value. */
  tone?: 'default' | 'bad' | 'good' | 'muted'
  strike?: boolean
  className?: string
}

const toneClass = { default: 'text-ink', bad: 'text-[var(--diff-bad)]', good: 'text-[var(--diff-good)]', muted: 'text-ink-3' }

/** Currency amount with tabular numerals. Shows "None" when the value is absent. */
export function Money({ cents, currency = 'USD', tone = 'default', strike, className }: MoneyProps) {
  return (
    <span className={cn('tabular whitespace-nowrap font-medium', toneClass[tone], strike && 'line-through decoration-1', className)}>
      {formatMoney(cents, currency)}
    </span>
  )
}
