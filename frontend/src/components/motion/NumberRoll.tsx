import { useEffect, useRef, useState } from 'react'
import { animate } from 'motion/react'
import { cn } from '@/lib/cn'
import { DUR, EASE, useMotionOK } from '@/lib/motion'

export interface NumberRollProps { value: number; format?: (n: number) => string; duration?: number; className?: string }
const integer = (n: number) => Math.round(n).toLocaleString('en-US')
export function NumberRoll({ value, format = integer, duration = DUR.base, className }: NumberRollProps) {
  const motionOK = useMotionOK()
  const [shown, setShown] = useState(value)
  const current = useRef(value)
  useEffect(() => {
    if (!motionOK || current.current === value) { current.current = value; setShown(value); return }
    const controls = animate(current.current, value, { duration, ease: EASE.out,
      onUpdate: (n) => { current.current = n; setShown(n) },
    })
    return () => controls.stop()
  }, [value, duration, motionOK])
  return <span className={cn('tabular', className)}>{format(shown)}</span>
}
export const AnimatedNumber = NumberRoll
export type AnimatedNumberProps = NumberRollProps
