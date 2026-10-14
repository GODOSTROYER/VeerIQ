import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { tint } from '@/lib/color'
import { TONE_COLOR, type Tone } from '@/lib/labels'

export interface BadgeProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'color'> {
  tone?: Tone
  /** Token reference; overrides tone. */
  color?: string
  icon?: ReactNode
  /** Dashed outline, used for simulated things. */
  dashed?: boolean
  size?: 'sm' | 'md'
  mono?: boolean
}

/** Small tinted label. Text is the full-strength hue on a low-alpha tint, which clears AA on the dark base. */
export function Badge({ tone = 'neutral', color, icon, dashed, size = 'md', mono, className, children, style, ...rest }: BadgeProps) {
  const c = color ?? TONE_COLOR[tone]
  return (
    <span
      className={cn(
        'inline-flex max-w-full items-center gap-1.5 whitespace-nowrap rounded-full border font-medium leading-none',
        size === 'sm' ? 'h-5 px-2 text-[11px]' : 'h-6 px-2.5 text-xs',
        mono && 'font-mono',
        dashed ? 'border-dashed' : 'border-solid',
        className,
      )}
      style={{ color: c, background: tint(c, 6), borderColor: tint(c, dashed ? 50 : 22), ...style }}
      {...rest}
    >
      {icon && <span className="inline-flex shrink-0 [&>svg]:size-3.5">{icon}</span>}
      <span className="truncate">{children}</span>
    </span>
  )
}
