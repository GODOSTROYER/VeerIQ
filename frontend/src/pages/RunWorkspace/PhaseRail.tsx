import { ArrowRight, Check, Minus, X } from 'lucide-react'
import { motion } from 'motion/react'
import { useMotionOK } from '@/lib/motion'
import type { RunView } from './model'
import type { RunStatus } from '@/api/types'
import { recordedVerification } from './stageModel'

export function PhaseRail({ view, finished, status = view.status }: { view: RunView; finished: boolean; status?: RunStatus }) {
  const motionOK = useMotionOK()
  const certified = finished && (status === 'succeeded' || status === 'partially_succeeded') && recordedVerification(view)
  const terminal = status === 'blocked' ? view.receipts.some(r => r.result === 'committed') ? 'Stopped after repair' : 'Stopped: no repair' : status === 'failed' ? 'Failed' : status === 'cancelled' ? 'Cancelled' : status === 'partially_succeeded' ? 'Partly repaired' : certified ? 'Certified' : 'Finished: verification not recorded'
  const phases = [
    { label: 'Authorize', done: true },
    { label: 'Plan signed', done: !!view.plan },
    { label: 'Inspect', done: view.proposals.some(p => p.tool === 'inspect_snapshot' && p.status === 'executed') },
    ...(view.blockedProposals ? [{ label: 'Trap blocked', done: true }] : []),
    { label: 'Repair prepared', done: view.manifests.length > 0 },
    ...(view.approvals.length || view.proposals.some(p => p.status === 'held') ? [{ label: 'Second person', done: view.approvals.some(a => a.status === 'approved') }] : []),
    { label: 'Committed', done: view.receipts.some(r => r.result === 'committed') },
    ...(finished && status === 'partially_succeeded' && certified ? [{ label: 'Certified', done: true }] : []),
    { label: finished ? terminal : 'Verification', done: certified && status !== 'partially_succeeded' },
  ]
  const current = finished ? phases.length - 1 : Math.max(0, phases.findIndex(p => !p.done))
  return <nav aria-label="Recovery phases" data-phase-rail className="h-[120px] overflow-y-auto py-1 sm:h-16 xl:h-8">
    <ol className="flex flex-wrap items-center gap-x-3 gap-y-2 sm:gap-x-4 sm:gap-y-3">
      {phases.map((phase, i) => <li key={phase.label} data-phase-state={phase.done ? 'completed' : finished ? i === current ? 'terminal' : 'not-reached' : i === current ? 'current' : 'pending'} aria-current={i === current ? 'step' : undefined} className="flex items-center gap-2 text-xs">
        <motion.span className="grid size-5 shrink-0 place-items-center rounded-full border" style={{ borderColor: phase.done ? 'var(--outcome-allow)' : i === current && finished && (status === 'blocked' || status === 'failed') ? 'var(--outcome-block)' : i === current ? 'var(--text-2)' : 'var(--border-strong)', color: phase.done ? 'var(--outcome-allow)' : i === current && finished && (status === 'blocked' || status === 'failed') ? 'var(--outcome-block)' : 'var(--text-2)' }} animate={motionOK && i === current && !finished ? { opacity: [1, .55, 1] } : { opacity: 1 }} transition={{ duration: 1.8, repeat: motionOK && i === current && !finished ? Infinity : 0 }}>
          {phase.done ? <Check className="size-3" aria-hidden /> : finished ? i === current ? <X className="size-3" aria-hidden /> : <Minus className="size-3" aria-hidden /> : <span className="size-1 rounded-full bg-current" />}
        </motion.span>
        <span className={phase.done || i === current ? 'text-ink' : 'text-ink-3'}>{phase.label}{finished && !phase.done && i !== current && <span className="text-ink-3"> · Not reached</span>}</span>
        {i < phases.length - 1 && <ArrowRight className="ml-1 hidden size-3 text-ink-3 sm:block" aria-hidden />}
      </li>)}
    </ol>
  </nav>
}
