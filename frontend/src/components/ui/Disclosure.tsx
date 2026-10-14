import { useId, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { Collapse } from '@/components/motion/Collapse'
import { cn } from '@/lib/cn'
import { TONE_COLOR, type Tone } from '@/lib/labels'

export interface DisclosureProps { summary: ReactNode; defaultOpen?: boolean; tone?: Tone; children: ReactNode; className?: string }
export function Disclosure({ summary, defaultOpen = false, tone = 'neutral', children, className }: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()
  return <div className={cn('rounded-xl border border-line bg-raised', className)}>
    <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}
      className="flex min-h-11 w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left text-[13px] font-medium text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink active:bg-surface-3">
      <span className="min-w-0">{summary}</span><ChevronDown aria-hidden className={cn('size-4 shrink-0 transition-transform duration-150', open && 'rotate-180')} style={{ color: TONE_COLOR[tone] }} />
    </button>
    <Collapse open={open} id={id}><div className="border-t border-line p-4">{children}</div></Collapse>
  </div>
}
