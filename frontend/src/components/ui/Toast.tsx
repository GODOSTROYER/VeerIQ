import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { CheckCircle2, CircleAlert, Info, X } from 'lucide-react'
import { TONE_COLOR, type Tone } from '@/lib/labels'
import { T, useMotionOK } from '@/lib/motion'

export interface ToastInput {
  title: string
  description?: string
  tone?: Extract<Tone, 'good' | 'bad' | 'info' | 'neutral' | 'hold'>
  /** ms; 0 keeps it until dismissed. */
  duration?: number
  /** Optional follow-up the toast offers, such as returning to the run. */
  action?: { label: string; onClick: () => void }
}

interface ToastItem extends ToastInput {
  id: number
}

interface ToastApi {
  push: (t: ToastInput) => void
  success: (title: string, description?: string) => void
  error: (title: string, description?: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const motionOK = useMotionOK()
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(1)

  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), [])
  const push = useCallback(
    (t: ToastInput) => {
      const id = nextId.current++
      setItems((xs) => [...xs.slice(-3), { ...t, id }])
      const ms = t.duration ?? (t.tone === 'bad' ? 7000 : 4200)
      if (ms > 0) window.setTimeout(() => dismiss(id), ms)
    },
    [dismiss],
  )
  const api = useMemo<ToastApi>(
    () => ({
      push,
      success: (title, description) => push({ title, description, tone: 'good' }),
      error: (title, description) => push({ title, description, tone: 'bad' }),
    }),
    [push],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(
        <div
          aria-live="polite"
          aria-atomic="false"
          className="pointer-events-none fixed inset-x-0 bottom-0 z-[90] flex flex-col items-end gap-2 p-4 sm:p-6"
        >
          <AnimatePresence initial={false}>
            {items.map((t) => {
              const tone = t.tone ?? 'neutral'
              const c = TONE_COLOR[tone]
              const Icon = tone === 'good' ? CheckCircle2 : tone === 'bad' ? CircleAlert : Info
              return (
                <motion.div
                  key={t.id}
                  layout={motionOK}
                  initial={{ opacity: 0, y: motionOK ? 12 : 0, scale: 1 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, x: motionOK ? 12 : 0, transition: T.fast }}
                  transition={T.base}
                  role={tone === 'bad' ? 'alert' : 'status'}
                  className="pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border border-line-strong bg-overlay p-4"
                >
                  <Icon className="mt-0.5 size-4 shrink-0" style={{ color: c }} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-ink">{t.title}</p>
                    {t.description && <p className="mt-0.5 text-[13px] leading-snug text-ink-2">{t.description}</p>}
                    {t.action && (
                      <button
                        type="button"
                        onClick={() => {
                          t.action?.onClick()
                          dismiss(t.id)
                        }}
                        className="mt-1.5 rounded text-[13px] font-medium text-ink underline underline-offset-4 hover:text-ink-2"
                      >
                        {t.action.label}
                      </button>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => dismiss(t.id)}
                    aria-label="Dismiss notification"
                    className="grid size-6 shrink-0 place-items-center rounded-md text-ink-3 hover:bg-surface-2 hover:text-ink active:bg-surface-3"
                  >
                    <X className="size-3.5" />
                  </button>
                </motion.div>
              )
            })}
          </AnimatePresence>
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  )
}
