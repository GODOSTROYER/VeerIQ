import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface PanelProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title?: ReactNode; subtitle?: ReactNode; icon?: ReactNode; actions?: ReactNode
  /** Stronger border on a solid surface. */ strong?: boolean
  /** Remove body padding, for tables. */ flush?: boolean
  /** Semantic colour for the header icon. */ accent?: string
  as?: 'section' | 'div' | 'article'
}
export function Panel({ title, subtitle, icon, actions, strong, flush, accent, as: Tag = 'section', className, children, style, ...rest }: PanelProps) {
  const hasHeader = title || subtitle || icon || actions
  return <Tag className={cn('relative min-w-0 rounded-2xl', strong ? 'glass-strong' : 'glass', className)} style={style} {...rest}>
    {hasHeader && <header className={cn('flex flex-wrap items-start justify-between gap-3 px-5 pt-5', flush ? 'pb-4' : 'pb-1')}>
      <div className="flex min-w-0 flex-1 items-start gap-2.5">
        {icon && <span className="mt-0.5 inline-flex shrink-0 text-ink-2 [&>svg]:size-4" style={accent ? { color: accent } : undefined}>{icon}</span>}
        <div className="min-w-0">{title && <h2 className="text-[15px] font-semibold leading-snug text-ink">{title}</h2>}{subtitle && <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{subtitle}</p>}</div>
      </div>{actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>}
    <div className={cn(flush ? '' : 'p-5', hasHeader && !flush && 'pt-4')}>{children}</div>
  </Tag>
}
export const Card = Panel
export type CardProps = PanelProps
export function PanelDivider({ className }: { className?: string }) { return <div role="separator" className={cn('h-px w-full bg-line', className)} /> }
export function Section({ title, aside, children }: { title: ReactNode; aside?: ReactNode; children: ReactNode }) {
  return <div><div className="mb-3 flex flex-wrap items-center justify-between gap-3"><h3 className="text-sm font-semibold text-ink">{title}</h3>{aside && <div className="text-xs text-ink-2">{aside}</div>}</div>{children}</div>
}
