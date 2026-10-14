import type { ReactNode } from 'react'
import type { RunStatus } from '@/api/types'
import { cn } from '@/lib/cn'
import { tint } from '@/lib/color'
import { RUN_STATUS, TONE_COLOR, type Tone } from '@/lib/labels'

export interface StatusPillProps {
  tone?: Tone
  children: ReactNode
  /** Pulsing dot for something live. */
  live?: boolean
  icon?: ReactNode
  className?: string
}

/** Status with a dot: calm for neutral/good, louder for bad. */
export function StatusPill({ tone = 'neutral', children, live, icon, className }: StatusPillProps) {
  const c = TONE_COLOR[tone]
  return (
    <span
      className={cn('inline-flex min-h-7 max-w-full items-center gap-2 rounded-full border px-2.5 py-1 text-[13px] font-medium', className)}
      style={{ color: c, background: tint(c, 6), borderColor: tint(c, 22) }}
    >
      {icon ?? <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full bg-current', live && 'pulse-dot')} />}
      {children}
    </span>
  )
}

/** Run status pill with human wording ("Waiting for reviewer", never "awaiting_approval"). */
export function RunStatusPill({ status, className }: { status: RunStatus; className?: string }) {
  const meta = RUN_STATUS[status]
  return (
    <StatusPill tone={meta.tone} live={meta.live} className={className}>
      {meta.label}
    </StatusPill>
  )
}
