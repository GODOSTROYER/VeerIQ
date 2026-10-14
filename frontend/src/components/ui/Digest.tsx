import { useEffect, useRef, useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { cn } from '@/lib/cn'
import { truncateDigest } from '@/lib/format'
import { Tooltip } from './Tooltip'

export interface DigestProps {
  value: string | null | undefined
  /** Characters of the hash kept at the start / end. */
  head?: number
  tail?: number
  /** Short noun used in the tooltip ("Copy snapshot digest"). */
  label?: string
  className?: string
}

/** A hash or id in monospace: truncated for the eye, complete on copy and in the tooltip. */
export function Digest({ value, head = 8, tail = 4, label = 'digest', className }: DigestProps) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  if (!value) return <span className="text-ink-3">None</span>

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setCopied(false), 1600)
    } catch {
      /* clipboard blocked: the full value is still in the tooltip */
    }
  }

  return (
    <span className={cn('inline-flex max-w-full items-center gap-1 align-middle', className)}>
      <Tooltip content={<span className="mono break-all">{value}</span>}>
        <code className="truncate rounded-md bg-sunken px-1.5 py-0.5 font-mono text-[12px] text-ink-2">
          {truncateDigest(value, head, tail)}
        </code>
      </Tooltip>
      <Tooltip content={copied ? 'Copied' : `Copy full ${label}`}>
        <button
          type="button"
          onClick={copy}
          aria-label={copied ? `Copied ${label}` : `Copy full ${label}`}
          className="grid size-6 shrink-0 place-items-center rounded-md text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink active:bg-surface-3"
        >
          {copied ? <Check className="size-3.5 text-allow" /> : <Copy className="size-3.5" />}
        </button>
      </Tooltip>
    </span>
  )
}
