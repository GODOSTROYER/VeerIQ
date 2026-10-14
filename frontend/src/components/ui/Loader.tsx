import { cn } from '@/lib/cn'

export interface LoaderProps { size?: 'sm' | 'md' | 'lg'; label?: string; className?: string }
const sizes = { sm: 20, md: 32, lg: 56 }
/** The shield stays anchored while its rewind arc conveys work in progress. */
export function Loader({ size = 'md', label = 'Loading VeerIQ', className }: LoaderProps) {
  return <span role="status" aria-label={label} className={cn('inline-flex shrink-0 items-center justify-center text-ink', className)}>
    <svg width={sizes[size]} height={sizes[size]} viewBox="0 0 40 40" fill="none" aria-hidden>
      <path d="M20 7 10 11v8c0 6 4 10 10 12 6-2 10-6 10-12v-8L20 7Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M24 17a5 5 0 1 0 .8 5M24.5 14.5v3.5H21" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <g className="loader-arc"><path d="M4 20a16 16 0 0 1 27-11M31 5v4h-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></g>
    </svg>
  </span>
}
