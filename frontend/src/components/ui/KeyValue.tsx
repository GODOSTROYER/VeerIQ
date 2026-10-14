import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface KeyValueProps {
  label: ReactNode
  children: ReactNode
  /** Render the value in monospace (use only for ids and hashes). */
  mono?: boolean
  hint?: ReactNode
  className?: string
}

/** One labelled fact. Label sits above the value so long values can wrap. */
export function KeyValue({ label, children, mono, hint, className }: KeyValueProps) {
  return (
    <div className={cn('min-w-0', className)}>
      <dt className="text-xs leading-relaxed text-ink-2">{label}</dt>
      <dd className={cn('mt-1 break-words text-sm text-ink', mono && 'font-mono text-[13px]')}>{children}</dd>
      {hint && <p className="mt-0.5 text-xs leading-relaxed text-ink-2">{hint}</p>}
    </div>
  )
}

/** Grid of KeyValue items. */
export function KeyValueGrid({ children, columns = 2, className }: { children: ReactNode; columns?: 1 | 2 | 3 | 4; className?: string }) {
  const cols = { 1: 'grid-cols-1', 2: 'grid-cols-1 sm:grid-cols-2', 3: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3', 4: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4' }[columns]
  return <dl className={cn('grid gap-x-6 gap-y-4', cols, className)}>{children}</dl>
}
