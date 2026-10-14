import { cn } from '@/lib/cn'

export interface AvatarProps {
  name: string
  /** Hex accent from the identity record. */
  color?: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

/** Initials are always derived from the displayed name so they can never disagree with it. */
export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

const sizes = { sm: 'size-6 text-[10px]', md: 'size-8 text-xs', lg: 'size-11 text-sm' }

export function Avatar({ name, color = 'var(--layer-runtime)', size = 'md', className }: AvatarProps) {
  return (
    <span
      aria-hidden
      className={cn('grid shrink-0 place-items-center rounded-full font-semibold', sizes[size], className)}
      style={{ color: `color-mix(in srgb, ${color} 65%, var(--text))`, background: `color-mix(in srgb, ${color} 13%, var(--bg-raised))` }}
    >
      {initialsOf(name)}
    </span>
  )
}
