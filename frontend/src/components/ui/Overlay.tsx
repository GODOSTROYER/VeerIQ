import { useEffect, useId, useRef, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { T } from '@/lib/motion'

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])'

/** Traps focus inside `ref`, closes on Escape, locks body scroll and restores focus on close. */
function useOverlayBehaviour(open: boolean, ref: RefObject<HTMLElement | null>, onClose: () => void, dismissable: boolean) {
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const node = ref.current
    const first = node?.querySelector<HTMLElement>('[data-autofocus]') ?? node?.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? node)?.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && dismissable) {
        e.stopPropagation()
        closeRef.current()
      }
      if (e.key !== 'Tab' || !node) return
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null)
      if (items.length === 0) {
        e.preventDefault()
        return
      }
      const a = items[0]
      const z = items[items.length - 1]
      if (e.shiftKey && document.activeElement === a) {
        e.preventDefault()
        z.focus()
      } else if (!e.shiftKey && document.activeElement === z) {
        e.preventDefault()
        a.focus()
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.body.style.overflow = prevOverflow
      previous?.focus?.()
    }
  }, [open, ref, dismissable])
}

export interface OverlayProps {
  open: boolean
  onClose: () => void
  title: ReactNode
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
  /** Set false while a request is running so the overlay cannot be dismissed mid-flight. */
  dismissable?: boolean
  className?: string
}

interface BaseProps extends OverlayProps {
  variant: 'modal' | 'drawer'
  width: string
}

function Base({ open, onClose, title, description, children, footer, dismissable = true, className, variant, width }: BaseProps) {
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const descId = useId()
  const reduce = useReducedMotion()
  useOverlayBehaviour(open, ref, onClose, dismissable)

  const panelMotion =
    reduce ? { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0, transition: T.fast } } : variant === 'modal'
      ? { initial: { opacity: 0, scale: 0.98 }, animate: { opacity: 1, y: 0, scale: 1 }, exit: { opacity: 0, scale: 0.98, transition: T.fast } }
      : { initial: { x: '100%' }, animate: { x: 0 }, exit: { x: '100%', transition: T.fast } }

  return createPortal(
    <AnimatePresence>
      {open && (
        <div className={cn('fixed inset-0 z-50 flex', variant === 'modal' ? 'items-center justify-center p-4 sm:p-8' : 'justify-end')}>
          <motion.div
            className="absolute inset-0 bg-[var(--scrim)] backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, transition: T.fast }}
            transition={T.base}
            onClick={dismissable ? onClose : undefined}
            aria-hidden
          />
          <motion.div
            ref={ref}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={description ? descId : undefined}
            tabIndex={-1}
            {...panelMotion}
            transition={T.base}
            className={cn(
              'relative flex max-h-full flex-col overflow-hidden border border-line-strong bg-overlay text-ink outline-none',
              variant === 'modal' ? 'w-full rounded-2xl' : 'h-full w-full',
              className,
            )}
            style={{ maxWidth: width }}
          >
            <header className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
              <div className="min-w-0">
                <h2 id={titleId} className="text-lg font-semibold leading-tight">
                  {title}
                </h2>
                {description && (
                  <p id={descId} className="mt-1 text-[13px] leading-snug text-ink-2">
                    {description}
                  </p>
                )}
              </div>
              {dismissable && (
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close"
                  className="grid size-8 shrink-0 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink active:bg-surface-3"
                >
                  <X className="size-4" />
                </button>
              )}
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
            {footer && <footer className="border-t border-line bg-sunken px-6 py-4">{footer}</footer>}
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  )
}

export interface ModalProps extends OverlayProps {
  /** Max width in CSS units. */
  width?: string
}

/** Centered dialog with focus trap, Escape to close and scroll lock. */
export function Modal({ width = '640px', ...rest }: ModalProps) {
  return <Base variant="modal" width={width} {...rest} />
}

export interface DrawerProps extends OverlayProps {
  width?: string
}

/** Right-hand drawer (evidence, details). Same behaviour as Modal. */
export function Drawer({ width = '560px', ...rest }: DrawerProps) {
  return <Base variant="drawer" width={width} {...rest} />
}
