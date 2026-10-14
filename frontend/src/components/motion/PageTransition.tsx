import type { ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useLocation } from 'react-router-dom'
import { DUR, EASE, useMotionOK } from '@/lib/motion'

export interface PageTransitionProps { children: ReactNode; className?: string }
export function PageTransition({ children, className }: PageTransitionProps) {
  const { pathname } = useLocation()
  const motionOK = useMotionOK()
  return <AnimatePresence mode="wait" initial={false}>
    <motion.div key={pathname} className={className}
      initial={{ opacity: 0, y: motionOK ? 6 : 0 }} animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, transition: { duration: DUR.fast, ease: EASE.exit } }}
      transition={{ duration: DUR.base, ease: EASE.out }}>{children}</motion.div>
  </AnimatePresence>
}
