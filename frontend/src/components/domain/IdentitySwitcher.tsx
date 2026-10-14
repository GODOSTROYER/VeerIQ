import { useId, useRef, useState } from 'react'
import { Check, ChevronDown, Loader2 } from 'lucide-react'
import { useSession } from '@/api/session'
import { cn } from '@/lib/cn'
import { tenantName } from '@/lib/labels'
import { perspective } from '@/lib/roles'
import { Avatar, useToast } from '@/components/ui'
import { errorMessage } from '@/api/client'
import { Popover } from '@/components/shell/Popover'

export interface IdentitySwitcherProps { className?: string }
/** Local demo perspectives; role and tenant authority stay visible in the chooser. */
export function IdentitySwitcher({ className }: IdentitySwitcherProps) {
  const { authMode, identity, identities, signIn, signOut } = useSession()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const anchor = useRef<HTMLButtonElement>(null)
  const menuId = useId()
  if (!identity) return null
  if (authMode === 'oidc') return <div className="flex items-center gap-2 text-sm"><span>{identity.name} · {identity.role}</span><button type="button" onClick={()=>void signOut()} className="min-h-10 px-3 text-ink-2 hover:bg-surface-2">Sign out</button></div>
  const me = perspective(identity)
  const choose = async (id: string) => {
    if (id === identity.identity_id) { setOpen(false); anchor.current?.focus(); return }
    setBusy(id)
    try { await signIn(id); setOpen(false); anchor.current?.focus() }
    catch (err) { toast.error('Could not switch perspective', errorMessage(err)) }
    finally { setBusy(null) }
  }
  return <div className={className}>
    <button ref={anchor} type="button" aria-label={`Viewing as ${me.label}: ${identity.name}. Switch perspective`} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined}
      onClick={() => setOpen((v) => !v)} onKeyDown={(e) => { if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true) } }}
      className="flex h-10 items-center gap-2 rounded-xl border border-line bg-raised py-1 pl-1.5 pr-2 transition-colors hover:bg-surface-2 hover:border-line-strong active:bg-surface-3">
      <Avatar name={identity.name} color={identity.color} />
      <span className="hidden text-left leading-tight md:block"><span className="block text-[11px] text-ink-3">Viewing as</span><span className="block text-[13px] font-medium text-ink">{me.label}</span></span>
      <ChevronDown aria-hidden className={cn('size-3.5 text-ink-3 transition-transform', open && 'rotate-180')} />
    </button>
    <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} id={menuId} label="Switch perspective" role="menu">
      <div className="border-b border-line px-5 py-4"><p className="text-[15px] font-semibold">Switch perspective</p><p className="mt-1 text-xs leading-relaxed text-ink-2">Authority depends on who is asking. Switch to see what each role can and cannot do. Demo identities, no real accounts.</p></div>
      <ul className="p-2">{identities.map((i) => {
        const active = i.identity_id === identity.identity_id
        const p = perspective(i)
        return <li key={i.identity_id}><button type="button" role="menuitemradio" aria-checked={active} aria-busy={busy === i.identity_id || undefined} disabled={busy !== null} onClick={() => void choose(i.identity_id)}
          className={cn('flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left transition-colors hover:bg-surface-2 active:bg-surface-3 disabled:opacity-50', active && 'bg-surface-2')}>
          <Avatar name={i.name} color={i.color} size="lg" /><span className="min-w-0 flex-1"><span className="block text-sm font-semibold">{p.label}</span><span className="mt-1 block text-xs leading-relaxed text-ink-2">{p.purpose}</span><span className="mt-1 block text-xs text-ink-3">{i.name} · {tenantName(i.tenant_id)}</span></span>
          {busy === i.identity_id ? <Loader2 aria-hidden className="mt-1 size-4 animate-spin" /> : active && <Check className="mt-1 size-4 shrink-0 text-allow" aria-label="Current perspective" />}
        </button></li>
      })}</ul>
    </Popover>
  </div>
}
