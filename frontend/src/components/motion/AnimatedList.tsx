import type { HTMLAttributes, ReactNode } from 'react'
import { AnimatePresence, motion, type HTMLMotionProps } from 'motion/react'
import { DUR, T, useMotionOK } from '@/lib/motion'
import { cn } from '@/lib/cn'

export interface AnimatedListProps extends HTMLAttributes<HTMLOListElement> { as?: 'ol' | 'ul'; children: ReactNode }
export function AnimatedList({ as: Tag = 'ol', children, ...props }: AnimatedListProps) {
  return <Tag {...props}><AnimatePresence initial={false}>{children}</AnimatePresence></Tag>
}
export interface AnimatedItemProps extends Omit<HTMLMotionProps<'li'>, 'id' | 'children'> { id: string; highlight?: string; children: ReactNode }
export function AnimatedItem({ id, highlight, children, className, ...props }: AnimatedItemProps) {
  const motionOK = useMotionOK()
  return <motion.li id={id} layout={motionOK} className={cn('relative isolate', className)}
    initial={{ height: motionOK ? 0 : 'auto', opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
    exit={{ height: motionOK ? 0 : 'auto', opacity: 0, transition: T.fast }}
    transition={{ ...T.base, layout: T.layout }} style={{ overflow: 'hidden' }} {...props}>
    {highlight && <motion.span aria-hidden className="pointer-events-none absolute inset-0 -z-10 rounded-[inherit]"
      style={{ background: highlight }} initial={{ opacity: motionOK ? 0.14 : 0.08 }} animate={{ opacity: 0 }}
      transition={{ duration: motionOK ? 1.2 : DUR.fast, ease: 'easeOut' }} />}
    {children}
  </motion.li>
}
