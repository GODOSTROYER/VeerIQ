import { useReducedMotion, type Variants } from 'motion/react'

export const DUR = { instant: 0.1, fast: 0.15, base: 0.22, slow: 0.36, focal: 0.64 }
export const EASE = { out: [0.16, 1, 0.3, 1], inOut: [0.65, 0, 0.35, 1], exit: [0.4, 0, 1, 1] } as const
export const T = {
  fast: { duration: DUR.fast, ease: EASE.out },
  base: { duration: DUR.base, ease: EASE.out },
  slow: { duration: DUR.slow, ease: EASE.out },
  layout: { type: 'spring', stiffness: 420, damping: 40, mass: 0.9 },
} as const
export const fadeRise: Variants = { hidden: { opacity: 0, y: 8 }, shown: { opacity: 1, y: 0, transition: T.base } }
export const fadeIn: Variants = { hidden: { opacity: 0 }, shown: { opacity: 1, transition: T.base } }
export function useMotionOK(): boolean { return !useReducedMotion() }
