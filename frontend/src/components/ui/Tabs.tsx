import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { motion } from 'motion/react'
import { cn } from '@/lib/cn'
import { T, useMotionOK } from '@/lib/motion'

export interface TabItem<T extends string = string> {
  id: T
  label: ReactNode
  count?: number
  icon?: ReactNode
  disabled?: boolean
}

export interface TabsProps<T extends string = string> {
  items: TabItem<T>[]
  value: T
  onChange: (id: T) => void
  /** Accessible name for the tab list. */
  label: string
  className?: string
}

/** Segmented tab list with arrow-key navigation. Render the active panel yourself. */
export function Tabs<T extends string = string>({ items, value, onChange, label, className }: TabsProps<T>) {
  const group = useId()
  const motionOK = useMotionOK()
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const enabled = items.filter((i) => !i.disabled)
    if (!enabled.length) return
    const idx = enabled.findIndex((i) => i.id === value)
    let next = -1
    if (e.key === 'ArrowRight') next = (idx + 1) % enabled.length
    else if (e.key === 'ArrowLeft') next = (idx - 1 + enabled.length) % enabled.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = enabled.length - 1
    if (next >= 0) {
      e.preventDefault()
      const id = enabled[next].id
      onChange(id)
      refs.current[id]?.focus()
    }
  }

  return (
    <div role="tablist" aria-label={label} onKeyDown={onKeyDown} className={cn('inline-flex max-w-full gap-1 overflow-x-auto rounded-xl border border-line bg-sunken p-1', className)}>
      {items.map((item) => {
        const active = item.id === value
        return (
          <button
            key={item.id}
            ref={(el) => {
              refs.current[item.id] = el
            }}
            role="tab"
            type="button"
            id={`${group}-${item.id}`}
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onChange(item.id)}
            className={cn(
              'relative inline-flex h-8 shrink-0 items-center gap-2 rounded-lg px-3 text-[13px] font-medium transition-colors hover:bg-surface-2 active:bg-surface-3 disabled:opacity-40',
              active ? 'text-ink' : 'text-ink-3 hover:text-ink-2',
            )}
          >
            {active && (
              <motion.span
                layoutId={motionOK ? `${group}-pill` : undefined}
                className="absolute inset-0 rounded-lg bg-surface-2"
                transition={T.base}
              />
            )}
            <span className="relative inline-flex items-center gap-2">
              {item.icon}
              {item.label}
              {item.count !== undefined && <span className="tabular rounded-full bg-surface-3 px-1.5 text-[11px] text-ink-2">{item.count}</span>}
            </span>
          </button>
        )
      })}
    </div>
  )
}
