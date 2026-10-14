import { motion } from 'motion/react'
import { T, useMotionOK } from '@/lib/motion'
import { Check, ShieldAlert } from 'lucide-react'
import type { InvariantCategory, InvariantCheck } from '@/api/types'
import { cn } from '@/lib/cn'
import { tint } from '@/lib/color'
import { INVARIANT_CATEGORY, INVARIANT_STATUS, TONE_COLOR } from '@/lib/labels'

export interface ProtectedChecklistProps {
  checks: InvariantCheck[]
  /** Only show these categories. */
  only?: InvariantCategory[]
  /** Hide these categories (e.g. hide "repair" where repairs are shown elsewhere). */
  exclude?: InvariantCategory[]
  /** One line per check, no detail text. */
  compact?: boolean
  className?: string
}

/**
 * Protected state: what must stay true. Preserved and repaired checks are calm green; a violated check is loud red
 * and announced to assistive tech. A violation should never happen: the loudness is the point.
 */
export function ProtectedChecklist({ checks, only, exclude, compact, className }: ProtectedChecklistProps) {
  const reduce = !useMotionOK()
  const visible = checks.filter((c) => (!only || only.includes(c.category)) && !exclude?.includes(c.category))
  if (!visible.length) return <p className="text-sm text-ink-3">No checks to show. Open the run’s evidence to inspect the protected state.</p>
  return (
    <ul className={cn('divide-y divide-line', className)}>
      {visible.map((check) => {
        const status = INVARIANT_STATUS[check.status]
        const violated = check.status === 'violated'
        const color = TONE_COLOR[status.tone]
        const Cat = INVARIANT_CATEGORY[check.category]?.icon
        return (
          <motion.li
            key={check.check_id}
            layout="position"
            initial={false}
            animate={{ opacity: 1, y: 0 }}
            transition={reduce ? { duration: 0 } : T.fast}
            role={violated ? 'alert' : undefined}
            className={cn('flex items-start gap-2 py-2', compact ? 'text-xs' : 'text-sm')}
            style={{
              background: violated ? tint(color, 12) : undefined,
            }}
          >
            <span className="mt-0.5 grid size-4 shrink-0 place-items-center" style={{ color, background: undefined }}>
              {violated ? <ShieldAlert className="size-4" aria-hidden /> : Cat ? <Cat className="size-4" aria-hidden /> : null}
            </span>
            <div className="min-w-0 flex-1">
              <p className={cn(compact ? 'text-xs leading-snug' : 'text-sm leading-snug', violated ? 'font-semibold text-ink' : 'font-medium text-ink')}>{check.label}</p>
              {!compact && check.detail && <p className="mt-0.5 text-[13px] leading-snug text-ink-3">{check.detail}</p>}
            </div>
            <span className="mt-0.5 inline-flex shrink-0 items-center gap-1 text-xs font-medium" style={{ color }}>
              {(check.status === 'preserved' || check.status === 'repaired') && <Check className="size-3.5" aria-hidden />}
              {status.label}
            </span>
          </motion.li>
        )
      })}
    </ul>
  )
}
