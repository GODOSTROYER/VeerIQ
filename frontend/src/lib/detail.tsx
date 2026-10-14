import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Collapse } from '@/components/motion/Collapse'
import { Tooltip } from '@/components/ui/Tooltip'
import { T } from './motion'

export interface DetailState { technical: boolean; setTechnical(v: boolean): void; toggle(): void }
const DetailContext = createContext<DetailState | null>(null)
const key = 'rewindsafe.detail'
export function DetailProvider({ children }: { children: ReactNode }) {
  const [technical, setTechnical] = useState(() => { try { return localStorage.getItem(key) === 'technical' } catch { return false } })
  const toggle = useCallback(() => setTechnical((v) => !v), [])
  useEffect(() => { try { localStorage.setItem(key, technical ? 'technical' : 'plain') } catch { /* storage is optional */ } }, [technical])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== 't' || e.repeat || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.defaultPrevented) return
      const target = e.target as HTMLElement | null
      if (target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"]')) return
      e.preventDefault(); toggle()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [toggle])
  const value = useMemo(() => ({ technical, setTechnical, toggle }), [technical, toggle])
  return <DetailContext.Provider value={value}>{children}</DetailContext.Provider>
}
export function useDetail(): DetailState {
  const value = useContext(DetailContext)
  if (!value) throw new Error('useDetail must be used inside <DetailProvider>')
  return value
}
export function Technical({ children, inline = false }: { children: ReactNode; inline?: boolean }) {
  const { technical } = useDetail()
  if (!inline) return <Collapse open={technical}>{children}</Collapse>
  return <AnimatePresence initial={false}>{technical && <motion.span key="technical" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: T.fast }} transition={T.base}>{children}</motion.span>}</AnimatePresence>
}
export function Plain({ children }: { children: ReactNode }) { return useDetail().technical ? null : <>{children}</> }
export function TechToggle() {
  const { technical, toggle } = useDetail()
  return <Tooltip content="Show ids, hashes, timings, policy names and raw reasons. Shortcut: T (outside text fields)." side="bottom">
    <button type="button" role="switch" aria-checked={technical} aria-keyshortcuts="T" onClick={toggle}
      className="tech-toggle inline-flex h-9 shrink-0 items-center gap-2 rounded-xl px-2 text-[13px] font-medium text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink active:bg-surface-3">
      <span>View details</span><span aria-hidden className="tech-track"><span className="tech-thumb" /></span>
    </button>
  </Tooltip>
}
