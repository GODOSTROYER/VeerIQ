import { useEffect, useState, type ReactNode } from 'react'
import { Moon, Sun } from 'lucide-react'
import { NavLink, useLocation } from 'react-router-dom'
import { motion } from 'motion/react'
import { useSession } from '@/api/session'
import { useApprovals, useSystemStatus } from '@/api/hooks'
import { cn } from '@/lib/cn'
import { TechToggle } from '@/lib/detail'
import { T, useMotionOK } from '@/lib/motion'
import { IdentitySwitcher, ModeBanner } from '@/components/domain'
import { Wordmark } from './Logo'
import { SystemPill } from './SystemPill'

interface NavItem { to: string; label: string; end?: boolean; badge?: number }
function NavItems({ items, orientation }: { items: NavItem[]; orientation: 'header' | 'row' }) {
  const { pathname } = useLocation()
  const motionOK = useMotionOK()
  return <nav aria-label="Main" className={cn('flex items-center gap-1', orientation === 'row' && 'justify-start overflow-x-auto')}>
    {items.map((item) => {
      const active = item.to === '/' ? pathname === '/' : item.to === '/workspace' ? pathname.startsWith('/workspace') || pathname.startsWith('/runs') : pathname.startsWith(item.to)
      return <NavLink key={item.to} to={item.to} end={item.end} aria-current={active ? 'page' : undefined}
        className={cn('relative inline-flex h-9 shrink-0 items-center gap-2 rounded-xl px-3 text-[13px] font-medium transition-colors hover:bg-surface-2 active:bg-surface-3', active ? 'text-ink' : 'text-ink-3 hover:text-ink')}>
        {active && <motion.span layoutId={motionOK ? `nav-active-${orientation}` : undefined} className="absolute inset-0 rounded-xl bg-surface-2" transition={T.base} />}
        <span className="relative">{item.label}</span>
        {!!item.badge && <span className="tabular relative grid h-[18px] min-w-[18px] place-items-center rounded-full px-1 text-[11px] font-semibold text-ink-inverse" style={{ background: 'var(--layer-approval)' }} aria-label={`${item.badge} waiting`}>{item.badge}</span>}
      </NavLink>
    })}
  </nav>
}
export function AppShell({ children }: { children: ReactNode }) {
  const [theme,setTheme]=useState(()=>{try{return localStorage.getItem('veeriq.theme')==='light'?'light':'dark'}catch{return 'dark'}})
  useEffect(()=>{document.documentElement.dataset.theme=theme;try{localStorage.setItem('veeriq.theme',theme)}catch{}},[theme])
  const { authMode } = useSession()
  const status = useSystemStatus()
  const pending = useApprovals('pending')
  const items: NavItem[] = [
    { to: '/', label: 'Start here', end: true }, { to: '/workspace', label: 'Workspace' }, { to: '/approvals', label: 'Approvals', badge: pending.data?.length ?? 0 },
    { to: '/import', label: 'Import' }, { to: '/walkthrough', label: 'Walkthrough' }, { to: '/proof', label: 'Proof' }, { to: '/how', label: 'How it works' },
  ]
  return <div className="min-h-screen">
    <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-xl focus:bg-primary focus:px-3 focus:py-2 focus:text-ink-inverse">Skip to content</a>
    <header className="sticky top-0 z-40 border-b border-line bg-raised">
      <div className="mx-auto flex h-16 w-full max-w-[1680px] items-center gap-2 px-3 sm:gap-5 sm:px-4 lg:px-8">
        <Wordmark />
        <div className="hidden xl:block"><NavItems items={items} orientation="header" /></div>
        <div className="ml-auto flex items-center gap-2">
          <SystemPill status={status.data} error={status.error} onRetry={() => void status.refetch()} />
          <button className="inline-flex size-9 items-center justify-center text-ink-2 hover:bg-surface-2" aria-label={`Switch to ${theme==='dark'?'light':'dark'} theme`} onClick={()=>setTheme(theme==='dark'?'light':'dark')}>{theme==='dark'?<Sun className="size-4"/>:<Moon className="size-4"/>}</button>
          <div className="hidden sm:block"><TechToggle /></div>
          <IdentitySwitcher />
        </div>
      </div>
      <div className="mx-auto flex max-w-[1680px] items-center justify-between gap-2 border-t border-line px-3 py-1 sm:hidden">
        <span className="text-xs text-ink-3">Evidence detail</span><TechToggle />
      </div>
      <div className="border-t border-line px-2 py-1 xl:hidden"><NavItems items={items} orientation="row" /><p className="px-3 pb-1 text-[11px] text-ink-3 sm:hidden">Swipe navigation for more</p></div>
    </header>
    <ModeBanner status={status.data} />
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1680px] px-4 pb-24 pt-8 outline-none sm:px-5 lg:px-8">{children}</main>
    <footer className="mx-auto flex max-w-[1680px] flex-wrap justify-between gap-3 border-t border-line px-5 py-6 text-xs text-ink-3"><span>Prepared incidents use synthetic data · {authMode==='oidc'?'Organization sign-in':'Local demo identities'}</span><span>Exact repair scope · Durable effects · Locally signed evidence</span></footer>
  </div>
}
