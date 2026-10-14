import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/cn'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline'
export type ButtonSize = 'sm' | 'md' | 'lg'
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  icon?: ReactNode
  iconRight?: ReactNode
}
const variants: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-ink-inverse hover:bg-[var(--primary-hover)] active:brightness-95',
  secondary: 'border border-line-strong bg-surface-2 text-ink hover:bg-surface-3 active:bg-surface',
  outline: 'border border-line-strong bg-transparent text-ink hover:bg-surface-2 active:bg-surface-3',
  ghost: 'bg-transparent text-ink-2 hover:bg-surface-2 hover:text-ink active:bg-surface-3',
  danger: 'border border-[color-mix(in_srgb,var(--outcome-block)_30%,transparent)] bg-[color-mix(in_srgb,var(--outcome-block)_8%,var(--bg-raised))] text-block hover:bg-[color-mix(in_srgb,var(--outcome-block)_15%,var(--bg-raised))] active:bg-[color-mix(in_srgb,var(--outcome-block)_20%,var(--bg-raised))]',
}
const sizes: Record<ButtonSize, string> = {
  sm: 'h-8 gap-1.5 rounded-xl px-3 text-[13px]',
  md: 'h-10 gap-2 rounded-xl px-4 text-sm',
  lg: 'h-12 gap-2.5 rounded-xl px-6 text-[15px]',
}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading, icon, iconRight, className, children, disabled, type = 'button', ...rest }, ref,
) {
  return <button ref={ref} type={type} disabled={disabled || loading} aria-busy={loading || undefined}
    className={cn('relative inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap font-medium transition-colors duration-150 disabled:pointer-events-none disabled:opacity-45', variants[variant], sizes[size], className)} {...rest}>
    {icon && <span className={cn('inline-flex shrink-0 [&>svg]:size-4', loading && 'opacity-0')}>{icon}</span>}
    <span className={cn('inline-flex items-center', loading && !icon && 'opacity-0')}>{children}</span>
    {iconRight && <span className={cn('inline-flex shrink-0 [&>svg]:size-4', loading && 'opacity-0')}>{iconRight}</span>}
    {loading && <span aria-hidden className={cn('pointer-events-none absolute inset-y-0 flex items-center', icon ? (size === 'lg' ? 'left-6' : size === 'sm' ? 'left-3' : 'left-4') : 'inset-x-0 justify-center')}><Loader2 className="size-4 animate-spin" /></span>}
  </button>
})
