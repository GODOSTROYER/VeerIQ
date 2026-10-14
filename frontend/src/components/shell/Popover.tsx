import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { T, useMotionOK } from '@/lib/motion'
import { cn } from '@/lib/cn'

export interface PopoverProps {
  open: boolean; onClose(): void; anchor: RefObject<HTMLButtonElement | null>
  id: string; label: string; children: ReactNode; role?: 'dialog' | 'menu'; className?: string
}
/** Non-modal shell popover: portal, viewport bounds, Escape, outside click and keyboard focus. */
export function Popover({ open, onClose, anchor, id, label, children, role = 'dialog', className }: PopoverProps) {
  const panel = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  close.current = onClose
  const [pos, setPos] = useState({ left: 16, top: 72 })
  const motionOK = useMotionOK()
  useLayoutEffect(() => {
    if (!open) return
    const position = () => {
      const r = anchor.current?.getBoundingClientRect()
      if (r) setPos({ left: Math.max(12, Math.min(r.right - 400, window.innerWidth - Math.min(400, window.innerWidth - 24) - 12)), top: r.bottom + 8 })
    }
    position()
    const node = panel.current
    ;(role === 'menu' ? node?.querySelector<HTMLElement>('[role="menuitemradio"]:not([disabled])') ?? node : node)?.focus({ preventScroll: true })
    const outside = (e: PointerEvent) => {
      if (document.querySelector('[aria-modal="true"]')) return
      if (!node?.contains(e.target as Node) && !anchor.current?.contains(e.target as Node)) close.current()
    }
    const onKey = (e: KeyboardEvent) => {
      if (document.querySelector('[aria-modal="true"]')) return
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close.current(); anchor.current?.focus() }
      if (role !== 'menu' || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return
      const items = Array.from(node?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]:not([disabled])') ?? [])
      if (!items.length) return
      const current = items.indexOf(document.activeElement as HTMLButtonElement)
      const next = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : (current + (e.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length
      e.preventDefault(); items[next].focus()
    }
    const onFocus = (e: FocusEvent) => {
      if (document.querySelector('[aria-modal="true"]')) return
      if (!node?.contains(e.target as Node) && !anchor.current?.contains(e.target as Node)) close.current()
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', onKey)
    document.addEventListener('focusin', onFocus)
    window.addEventListener('resize', position)
    window.addEventListener('scroll', position, true)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('focusin', onFocus)
      window.removeEventListener('resize', position)
      window.removeEventListener('scroll', position, true)
    }
  }, [open, anchor, role])
  return createPortal(<AnimatePresence initial={false}>{open && <motion.div ref={panel} id={id} role={role} aria-label={label} tabIndex={-1}
    initial={{ opacity: 0, scale: motionOK ? 0.98 : 1 }} animate={{ opacity: 1, scale: 1 }}
    exit={{ opacity: 0, transition: T.fast }} transition={T.base}
    className={cn('fixed z-50 w-[400px] max-w-[calc(100vw-24px)] origin-top-right overflow-y-auto rounded-2xl border border-line-strong bg-overlay text-ink outline-none', className)}
    style={{ left: pos.left, top: pos.top, maxHeight: `calc(100dvh - ${pos.top + 12}px)` }}>{children}</motion.div>}</AnimatePresence>, document.body)
}
