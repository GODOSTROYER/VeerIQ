import type { ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { DUR, T, useMotionOK } from '@/lib/motion'

export interface CollapseProps { open: boolean; children: ReactNode; className?: string; id?: string }
export function Collapse({ open, children, className, id }: CollapseProps) {
  const motionOK = useMotionOK()
  return <AnimatePresence initial={false}>
    {open && <motion.div id={id} key="content" className={className} style={{ overflow: 'hidden' }}
      initial={{ height: motionOK ? 0 : 'auto', opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
      exit={{ height: motionOK ? 0 : 'auto', opacity: 0, transition: T.fast }}
      transition={{ ...T.base, duration: motionOK ? DUR.base : DUR.instant }}>{children}</motion.div>}
  </AnimatePresence>
}
