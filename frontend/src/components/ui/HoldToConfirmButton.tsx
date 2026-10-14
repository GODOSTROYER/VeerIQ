import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { Check, Loader2 } from 'lucide-react'
import { cn } from '@/lib/cn'

export interface HoldToConfirmButtonProps {
  /** Fires once when the hold completes. */
  onConfirm: () => void
  children: ReactNode
  /** Label while the user is holding. */
  holdLabel?: string
  /** Hold duration in ms. */
  duration?: number
  disabled?: boolean
  loading?: boolean
  icon?: ReactNode
  className?: string
  /** Accessible hint, read by screen readers. */
  hint?: string
}

/**
 * Press-and-hold confirmation: a ring fills while the pointer (or Space/Enter) is
 * held, and the action fires only when it completes. Releasing early cancels, which
 * makes irreversible actions deliberate without a second dialog.
 */
export function HoldToConfirmButton({
  onConfirm,
  children,
  holdLabel = 'Keep holding',
  duration = 1100,
  disabled,
  loading,
  icon,
  className,
  hint = 'Press and hold to confirm',
}: HoldToConfirmButtonProps) {
  const [progress, setProgress] = useState(0)
  const [holding, setHolding] = useState(false)
  const [done, setDone] = useState(false)
  const raf = useRef<number | undefined>(undefined)
  const start = useRef(0)
  const fired = useRef(false)
  const confirmRef = useRef(onConfirm)
  confirmRef.current = onConfirm
  const inert = disabled || loading || done

  const cancel = useCallback(() => {
    if (raf.current) cancelAnimationFrame(raf.current)
    raf.current = undefined
    setHolding(false)
    if (!fired.current) setProgress(0)
  }, [])

  const tick = useCallback(
    (now: number) => {
      const p = Math.min(1, (now - start.current) / duration)
      setProgress(p)
      if (p >= 1) {
        fired.current = true
        raf.current = undefined
        setHolding(false)
        setDone(true)
        confirmRef.current()
        return
      }
      raf.current = requestAnimationFrame(tick)
    },
    [duration],
  )

  const begin = useCallback(() => {
    if (inert || holding) return
    fired.current = false
    setHolding(true)
    start.current = performance.now()
    raf.current = requestAnimationFrame(tick)
  }, [inert, holding, tick])

  useEffect(
    () => () => {
      if (raf.current) cancelAnimationFrame(raf.current)
    },
    [],
  )
  useEffect(() => { if (disabled || loading) cancel() }, [disabled, loading, cancel])
  // Re-arm after the parent finishes handling a confirm (e.g. a failed request).
  useEffect(() => {
    if (!loading && done) {
      const t = window.setTimeout(() => {
        setDone(false)
        setProgress(0)
        fired.current = false
      }, 600)
      return () => window.clearTimeout(t)
    }
  }, [loading, done])

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) {
      e.preventDefault()
      begin()
    }
  }
  const onKeyUp = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === ' ' || e.key === 'Enter') cancel()
  }
  const onPointerDown = (e: PointerEvent<HTMLButtonElement>) => {
    if (e.button !== 0) return
    e.currentTarget.setPointerCapture?.(e.pointerId)
    begin()
  }

  const r = 11
  const c = 2 * Math.PI * r

  return (
    <button
      type="button"
      disabled={inert}
      aria-busy={loading || undefined}
      aria-label={typeof children === 'string' ? `${children}. ${hint}` : hint}
      onPointerDown={onPointerDown}
      onPointerUp={cancel}
      onPointerCancel={cancel}
      onPointerLeave={cancel}
      onKeyDown={onKeyDown}
      onKeyUp={onKeyUp}
      onBlur={cancel}
      onContextMenu={(e) => e.preventDefault()}
      className={cn(
        'group relative inline-flex h-12 select-none items-center justify-center gap-3 overflow-hidden rounded-xl px-6 text-[15px] font-semibold',
        'bg-primary text-ink-inverse transition-colors duration-150 hover:bg-white active:bg-[#d5d9e4]',
        'touch-none disabled:pointer-events-none disabled:opacity-45',
        holding && 'bg-white',
        className,
      )}
    >
      {/* fill sweep */}
      <span
        aria-hidden
        className="absolute inset-0 origin-left bg-[color-mix(in_srgb,var(--layer-armoriq)_30%,var(--primary))]"
        style={{ transform: `scaleX(${progress})` }}
      />
      <span className="relative grid size-6 place-items-center">
        {loading ? (
          <Loader2 className="size-5 animate-spin" aria-hidden />
        ) : done ? (
          <Check className="size-5" aria-hidden />
        ) : (
          <>
            <svg viewBox="0 0 28 28" className="absolute inset-[-2px] size-7 -rotate-90" aria-hidden>
              <circle cx="14" cy="14" r={r} fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2.2" />
              <circle
                cx="14"
                cy="14"
                r={r}
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeDasharray={c}
                strokeDashoffset={c * (1 - progress)}
              />
            </svg>
            <span className="relative [&>svg]:size-3.5">{icon}</span>
          </>
        )}
      </span>
      <span className="relative">{holding ? holdLabel : children}</span>
    </button>
  )
}
