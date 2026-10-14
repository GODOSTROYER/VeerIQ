import { useEffect, useState, type ReactNode } from 'react'
import { motion } from 'motion/react'
import type { Metrics, SystemStatus, VerificationRun } from '@/api/types'
import { Loader, Skeleton } from '@/components/ui'
import { NumberRoll } from '@/components/motion'
import { useMotionOK } from '@/lib/motion'
import { formatDuration } from '@/lib/format'
export function SummaryBand({ run, metrics, status, running, starting, action }: { run: VerificationRun | null | undefined; metrics: Metrics | undefined; status: SystemStatus | undefined; running: boolean; starting: boolean; action: ReactNode }) {
  const motionOK = useMotionOK()
  const [now, setNow] = useState(Date.now())
  useEffect(() => { if (!running && !starting) return; setNow(Date.now()); const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer) }, [running, starting])
  const rows = run?.results ?? []
  const passed = rows.filter(r => r.passed).length
  const total = typeof run?.summary.total === 'number' && run.summary.total > 0 ? run.summary.total : null
  const attacks = metrics?.blocked_proposals ?? metrics?.forbidden_proposals ?? (metrics?.blocked_by_layer ? Object.values(metrics.blocked_by_layer).reduce<number>((n, v) => n + (v ?? 0), 0) : undefined)
  const mode = run?.enforcement_mode ?? status?.enforcement.mode
  const elapsed = run?.started_at ? Math.max(0, now - new Date(run.started_at).getTime()) : null
  return <section aria-label="Verification summary" className="rounded-2xl border border-line bg-raised px-5 py-5 sm:px-6">
    <div className="flex flex-wrap items-center justify-between gap-5">
      <div className="flex-1">
        {!run ? <p className="text-lg font-medium text-ink">No verified guarantees recorded yet</p> : <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-lg font-medium text-ink"><span><NumberRoll value={passed} /> {total !== null || !running ? <>of {total ?? rows.length} guarantees {running ? 'verified so far' : 'verified'}</> : 'guarantees verified so far; total not reported'}</span><span aria-hidden className="text-ink-3">·</span><span>{attacks === undefined ? 'Attacks not recorded' : <><NumberRoll value={attacks} /> attacks refused</>}</span><span aria-hidden className="text-ink-3">·</span><span>{metrics?.forbidden_effects_observed === undefined ? 'Effects not recorded' : <><NumberRoll value={metrics.forbidden_effects_observed} /> forbidden effects</>}</span><span aria-hidden className="text-ink-3">·</span><span className={mode === 'offline' ? 'text-hold' : 'text-ink-2'}>{mode === 'live' ? 'live ArmorIQ' : mode === 'offline' ? 'simulated ArmorIQ' : 'ArmorIQ mode unavailable'}</span></p>}
        {!metrics && <Skeleton className="mt-3 h-3 w-2/3" />}
        <p className="mt-2 text-xs text-ink-3">Guarantees belong to this suite; attack and effect counts cover recorded runs.</p>
      </div>{action}
    </div>
    {(running || starting) && <div className="mt-5 border-t border-line pt-4" role="status" aria-live="polite">
      <div className="flex items-center gap-3"><Loader size="sm" label="Verifying guarantees" /><div><p className="text-sm font-medium text-ink">{starting ? 'Starting verification' : 'Verification is running'}{elapsed !== null && running && <span className="tabular text-ink-2"> · {formatDuration(elapsed)} elapsed</span>}</p><p className="mt-1 text-[13px] text-ink-2">{rows.length} checks finished. The suite can take several minutes; it does not report the active check.</p></div></div>
      <div className="mt-3 h-1 overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-label="Verification progress" aria-valuemin={0} aria-valuemax={total ?? undefined} aria-valuenow={total ? rows.length : undefined} aria-valuetext={rows.length + ' checks completed' + (total ? ' of ' + total : '; total progress unknown')}>
        <motion.div className={total ? 'h-full w-full origin-left bg-[var(--layer-armoriq)]' : 'h-full w-1/3 bg-[var(--layer-armoriq)]'} animate={total ? { x: 0, scaleX: Math.min(1, rows.length / total) } : motionOK ? { x: ['-100%', '300%'], scaleX: 1 } : { x: '100%', scaleX: 1 }} transition={total ? { duration: motionOK ? 0.22 : 0 } : motionOK ? { duration: 1.8, ease: 'linear', repeat: Infinity } : { duration: 0 }} />
      </div>
    </div>}
    {run?.status === 'blocked' && <p className="mt-3 text-[13px] text-hold">The suite was blocked before verification could finish. Open suite details for the recorded reason.</p>}
  </section>
}
