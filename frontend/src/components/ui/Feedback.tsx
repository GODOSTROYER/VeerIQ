import type { ReactNode } from 'react'
import { CircleAlert, Inbox, RefreshCw, WifiOff } from 'lucide-react'
import { ApiError } from '@/api/client'
import { cn } from '@/lib/cn'
import { Button } from './Button'

/** Shimmering placeholder block. Size it with className. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('skeleton rounded-xl', className)} />
}

export function SkeletonLines({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn('space-y-2.5', className)} role="status" aria-label="Loading">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn('h-3.5', i === lines - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  )
}

export interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
  compact?: boolean
}

/** An empty list is an invitation: say what belongs here and offer the next step. */
export function EmptyState({ icon, title, description, action, className, compact }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center text-center', compact ? 'gap-2.5 px-4 py-8' : 'gap-3.5 px-5 py-12', className)}>
      <div className="grid size-11 place-items-center rounded-xl bg-surface-2 text-ink-3">
        {icon ?? <Inbox className="size-5" />}
      </div>
      <div className="max-w-sm">
        <p className="text-sm font-semibold text-ink">{title}</p>
        {description && <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{description}</p>}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}

export interface ErrorStateProps {
  error?: unknown
  title?: string
  onRetry?: () => void
  className?: string
  compact?: boolean
}

/** Explains what failed and how to recover. A dropped backend connection reads differently from a server error. */
export function ErrorState({ error, title, onRetry, className, compact }: ErrorStateProps) {
  const disconnected = error instanceof ApiError && error.isNetwork
  const message = error instanceof Error ? error.message : 'Something went wrong while loading this.'
  return (
    <div
      role="alert"
      className={cn('flex flex-col items-center justify-center text-center', compact ? 'gap-2.5 px-4 py-8' : 'gap-3.5 px-5 py-12', className)}
    >
      <div
        className="grid size-11 place-items-center rounded-2xl border"
        style={{
          color: disconnected ? 'var(--outcome-unavailable)' : 'var(--outcome-block)',
          borderColor: 'color-mix(in srgb, currentColor 35%, transparent)',
          background: 'color-mix(in srgb, currentColor 10%, transparent)',
        }}
      >
        {disconnected ? <WifiOff className="size-5" /> : <CircleAlert className="size-5" />}
      </div>
      <div className="max-w-md">
        <p className="text-sm font-semibold text-ink">{title ?? (disconnected ? 'Backend disconnected' : 'This did not load')}</p>
        <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{message}</p>
      </div>
      {onRetry && (
        <Button size="sm" variant="secondary" icon={<RefreshCw className="size-3.5" />} onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}
