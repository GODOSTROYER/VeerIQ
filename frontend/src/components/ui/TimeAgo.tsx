import { useEffect, useState } from 'react'
import { formatDateTime, relativeTime } from '@/lib/format'
import { Tooltip } from './Tooltip'
import { cn } from '@/lib/cn'

export interface TimeAgoProps {
  value: string | null | undefined
  className?: string
}

/** Relative time that stays fresh; the exact UTC timestamp is in the tooltip. */
export function TimeAgo({ value, className }: TimeAgoProps) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(id)
  }, [])
  if (!value) return <span className={className}>None</span>
  return (
    <Tooltip content={formatDateTime(value)}>
      <time dateTime={value} className={cn("tabular", className)} tabIndex={0}>
        {relativeTime(value, now)}
      </time>
    </Tooltip>
  )
}
