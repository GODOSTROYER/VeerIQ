import { cloneElement, useCallback, useEffect, useId, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/cn'

export interface TooltipProps {
  content: ReactNode
  children: ReactElement<Record<string, unknown>>
  side?: 'top' | 'bottom'
  /** ms before showing on hover */
  delay?: number
  className?: string
  disabled?: boolean
}

type Handler = ((e: unknown) => void) | undefined

/** Hover and focus tooltip rendered in a portal so cards never clip it. */
export function Tooltip({ content, children, side = 'top', delay = 250, className, disabled }: TooltipProps) {
  const id = useId()
  const ref = useRef<HTMLElement | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const [pos, setPos] = useState<{ x: number; y: number; place: 'top' | 'bottom' } | null>(null)

  const show = useCallback(() => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      const el = ref.current
      if (!el) return
      const r = el.getBoundingClientRect()
      const place = side === 'top' && r.top < 80 ? 'bottom' : side
      setPos({ x: Math.max(Math.min(160, (window.innerWidth - 24) / 2) + 12, Math.min(r.left + r.width / 2, window.innerWidth - Math.min(160, (window.innerWidth - 24) / 2) - 12)), y: place === 'top' ? r.top - 8 : r.bottom + 8, place })
    }, delay)
  }, [delay, side])
  const hide = useCallback(() => {
    window.clearTimeout(timer.current)
    setPos(null)
  }, [])

  useEffect(() => () => window.clearTimeout(timer.current), [])
  useEffect(() => {
    if (!pos) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && hide()
    window.addEventListener('keydown', onKey)
    window.addEventListener('scroll', hide, true)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', hide, true)
    }
  }, [pos, hide])

  if (disabled || !content) return children

  const own = children.props as {
    onMouseEnter?: Handler
    onMouseLeave?: Handler
    onFocus?: Handler
    onBlur?: Handler
  }
  const trigger = cloneElement(children, {
    ref: (node: HTMLElement | null) => {
      ref.current = node
    },
    'aria-describedby': pos ? id : undefined,
    onMouseEnter: (e: unknown) => {
      own.onMouseEnter?.(e)
      show()
    },
    onMouseLeave: (e: unknown) => {
      own.onMouseLeave?.(e)
      hide()
    },
    onFocus: (e: unknown) => {
      own.onFocus?.(e)
      show()
    },
    onBlur: (e: unknown) => {
      own.onBlur?.(e)
      hide()
    },
  })

  return (
    <>
      {trigger}
      {pos &&
        createPortal(
          <div
            id={id}
            role="tooltip"
            className={cn(
              'pointer-events-none fixed z-[100] max-w-[min(320px,calc(100vw-24px))] rounded-xl border border-line-strong bg-overlay px-3 py-2 text-xs leading-snug text-ink',
              className,
            )}
            style={{ left: pos.x, top: pos.y, transform: `translate(-50%, ${pos.place === 'top' ? '-100%' : '0'})` }}
          >
            {content}
          </div>,
          document.body,
        )}
    </>
  )
}
