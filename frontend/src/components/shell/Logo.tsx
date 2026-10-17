import { Link } from 'react-router-dom'
import { cn } from '@/lib/cn'

/**
 * The rewind-shield glyph: a shield (the defense) containing a counter-clockwise
 * arrow (the rewind). The violet-to-teal stroke runs from ArmorIQ's colour to PostgreSQL's,
 * the outermost and innermost layers of the defense stack.
 */
export function RewindShield({ size = 28, className }: { size?: number; className?: string }) {
  return <svg width={size} height={size} viewBox="0 0 32 32" fill="none" className={className} aria-hidden>
    <path d="M16 3 27 8v9c0 6-6 10-11 13C11 27 5 23 5 17V8L16 3Z" stroke="var(--layer-armoriq)" strokeWidth="1.7" strokeLinejoin="round" />
    <path d="m10 11 6 11 6-11" stroke="var(--layer-armoriq)" strokeWidth="2" strokeLinejoin="round" />
  </svg>
}

export function Wordmark({ className, linked = true }: { className?: string; linked?: boolean }) {
  const content = (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <RewindShield />
      <span className="veeriq-wordmark">VeerIQ</span>
    </span>
  )
  return linked ? (
    <Link to="/" aria-label="VeerIQ, go to the start page" className="rounded-lg">
      {content}
    </Link>
  ) : (
    content
  )
}
