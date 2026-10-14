import { Link } from 'react-router-dom'
import { motion } from 'motion/react'
import { Bot, ChevronLeft, Download, FastForward, FileSearch, FlaskConical, History, Pause, Play, ShieldCheck, Square, X } from 'lucide-react'
import type { PlanBinding, Run, RunStatus } from '@/api/types'
import { formatDateTime } from '@/lib/format'
import { isSimulatedEnforcement, type EnforcementFacts } from '@/lib/layers'
import { Badge, Button, Digest, Modal, RunStatusPill, StatusPill, TimeAgo, Tooltip } from '@/components/ui'
import { Technical } from '@/lib/detail'
import { T, useMotionOK } from '@/lib/motion'
import { REPLAY_SPEED, type ReplayState } from './hooks'

/** Planner wording the demo relies on: an LLM is never implied when none is used. */
export function plannerBadgeText(run: Run): string {
  const base = plannerBaseText(run)
  return run.planner_kind === 'harness' ? `Boundary test · ${base}` : `Recovery agent · ${base}`
}

function plannerBaseText(run: Run): string {
  if (run.planner_kind === 'scripted') return 'Scripted re-enactment (deterministic, no LLM)'
  if (run.planner_kind === 'harness') return 'Boundary harness — fixed probes, no LLM'
  const label = run.metadata?.planner_label
  if (typeof label === 'string' && label.trim()) return label
  const model = run.planner.includes(':') ? run.planner.split(':').slice(1).join(':') : run.planner
  return `Live LLM - ${model}`
}

function PlannerBadge({ run }: { run: Run }) {
  const llm = run.planner_kind === 'llm'
  const briefing = run.metadata?.agent_briefing
  const briefingNote =
    briefing === 'task_only'
      ? ' It was told the task, not the security rules, the way most production agents are prompted. The rules live in the enforcement layers.'
      : briefing === 'with_rules'
        ? " It was also told the grant's rules up front."
        : ''
  return (
    <Tooltip
      content={
        llm
          ? `A language model chose these steps. Whatever it asks for is still checked by every layer.${briefingNote}`
          : `No language model chose these steps. ${run.planner_kind === 'harness' ? 'The test harness runs fixed boundary probes.' : 'The agent follows a scripted re-enactment.'} Enforcement is checked separately.${briefingNote}`
      }
    >
      <span className="inline-flex">
        <Badge tone="neutral" icon={<Bot />} className="max-w-full whitespace-normal">
          {plannerBadgeText(run)}
        </Badge>
      </span>
    </Tooltip>
  )
}

function RunEnforcementBadge({ enforcement }: { enforcement: EnforcementFacts }) {
  if (isSimulatedEnforcement(enforcement)) {
    return (
      <Tooltip content="ArmorIQ decisions in this run come from a local simulation. No call was made to the ArmorIQ service.">
        <span className="inline-flex">
          <Badge tone="hold" dashed icon={<FlaskConical />}>
            Simulated ArmorIQ
          </Badge>
        </span>
      </Tooltip>
    )
  }
  return (
    <Tooltip content="Plans are signed by ArmorIQ. Off-plan tools are refused by the SDK against that plan, and in-plan calls are checked by ArmorIQ’s policy service.">
      <span className="inline-flex">
        <Badge color="var(--layer-armoriq)" icon={<ShieldCheck />}>
          Live ArmorIQ
        </Badge>
      </span>
    </Tooltip>
  )
}

export interface RunHeaderProps {
  run: Run
  title: string
  /** Internal id shown as secondary monospace text under the title (import runs). */
  rawId?: string
  /** Shared facts behind every "Live" or "Simulated" label on the page. */
  enforcement: EnforcementFacts
  status: RunStatus
  plan: PlanBinding | undefined
  steps: number
  maxSteps: number | undefined
  replans: number
  maxReplans: number | undefined
  live: boolean
  replay: ReplayState
  canReplay: boolean
  canCancel: boolean
  starterName: string
  onCancel: () => void
  onOpenEvidence: () => void
  onExport: () => void
  exporting: boolean
  applying?: boolean
}

export function RunHeader(p: RunHeaderProps) {
  const { run, plan } = p
  return (
    <header>
      <Link to="/" className="inline-flex items-center gap-1 rounded-md text-[13px] text-ink-3 transition-colors hover:text-ink">
        <ChevronLeft className="size-4" aria-hidden />
        Workspace
      </Link>

      <div className="mt-2 flex flex-col items-start justify-between gap-x-6 gap-y-3 sm:flex-row sm:flex-wrap">
        <div className="min-w-0 w-full sm:w-auto sm:flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 className="text-[24px] font-semibold leading-tight tracking-[-0.03em] text-ink">{p.title}</h1>
            {p.applying ? <StatusPill tone="info" live={p.live && !p.replay.active}>Applying repair</StatusPill> : <RunStatusPill status={p.status} />}
            {p.live && !p.replay.active && <span role="status" className="inline-flex items-center gap-1.5 text-xs text-allow"><span className="size-1.5 rounded-full bg-allow" aria-hidden />Live</span>}
          </div>
          {p.rawId && <p className="mt-1 break-all font-mono text-xs text-ink-3">{p.rawId}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <PlannerBadge run={run} />
            <RunEnforcementBadge enforcement={p.enforcement} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {p.canCancel && (
            <Button variant="danger" size="sm" icon={<X className="size-4" />} onClick={p.onCancel}>
              Cancel run
            </Button>
          )}
          {p.canReplay && !p.replay.active && (
            <Button variant="primary" size="sm" icon={<History className="size-4" />} onClick={p.replay.start}>
              Replay at {REPLAY_SPEED}x
            </Button>
          )}
          <Button variant="secondary" size="sm" icon={<FileSearch className="size-4" />} onClick={p.onOpenEvidence}>
            Evidence
          </Button>
          <Button variant="outline" size="sm" icon={<Download className="size-4" />} loading={p.exporting} onClick={p.onExport}>
            Export
          </Button>
        </div>
      </div>

      {run.metadata?.agent_briefing === 'task_only' && <p className="mt-2 text-xs text-ink-2">Task-only brief: the agent was told what to repair, not the security rules. The gates enforce those rules.</p>}
      {run.metadata?.agent_briefing === 'with_rules' && <p className="mt-2 text-xs text-ink-2">The agent was told the task and the grant’s rules.</p>}
      <dl className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-2.5 text-xs text-ink-3">
        <div className="flex items-center gap-1.5">
          <dt>Signed plan</dt>
          <dd>
            <span className="text-ink-2">{plan?.plan_hash ? `${plan.steps.length} actions allowed` : p.live || p.replay.active ? 'Waiting for signature' : 'Not bound'}</span>
          </dd>
        </div>
        <div className="flex items-center gap-1.5">
          <dt>Steps</dt>
          <dd className="tabular text-ink-2">
            {p.steps}
            {p.maxSteps !== undefined ? <span className="text-ink-3"> of {p.maxSteps}</span> : null}
          </dd>
        </div>
        <div className="flex items-center gap-1.5">
          <dt>Plan revisions</dt>
          <dd className="tabular text-ink-2">
            {p.replans}
            {p.maxReplans !== undefined ? <span className="text-ink-3"> of {p.maxReplans}</span> : null}
          </dd>
        </div>
        <div className="flex items-center gap-1.5">
          <dt>Started by {p.starterName}</dt>
          <dd className="text-ink-2">
            <TimeAgo value={run.created_at} />
          </dd>
        </div>
      </dl>
      <Technical><div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-3"><span className="break-all font-mono">{run.run_id}</span>{plan?.plan_hash && <Digest value={plan.plan_hash} label="signed plan hash" />}{plan?.expires_at && <span>Plan expires {formatDateTime(plan.expires_at)}</span>}</div></Technical>
    </header>
  )
}

/* ─── Replay ─── */

export function ReplayBar({ run, replay }: { run: Run; replay: ReplayState }) {
  const motionOK = useMotionOK()
  const ratio = replay.total > 0 ? Math.min(1, replay.cursor / replay.total) : 0
  const done = replay.cursor >= replay.total
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={T.fast}
      className="rounded-xl border border-line bg-raised px-4 py-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-ink">
            {done ? 'Replay complete' : replay.playing ? 'Replaying recorded steps' : 'Replay paused'} <span className="ml-2 text-xs font-normal text-ink-3">{replay.cursor} of {replay.total} events</span>
          </p>
          <Technical><p className="mt-1 break-all text-xs text-ink-3"><span className="font-mono">{run.run_id}</span> · Recorded {formatDateTime(run.created_at)}</p></Technical>
          <p className="mt-0.5 text-xs text-ink-3">
            {done
              ? 'Replay finished. This is the recorded run, not a new one.'
              : `Playing the recorded events at ${REPLAY_SPEED}x. Nothing is being re-executed.`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" icon={replay.playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />} onClick={replay.toggle}>
            {replay.playing ? 'Pause' : done ? 'Replay again' : 'Resume'}
          </Button>
          <Button size="sm" variant="ghost" icon={<FastForward className="size-3.5" />} onClick={replay.skipToEnd} disabled={done}>
            Skip to end
          </Button>
          <Button size="sm" variant="outline" icon={<Square className="size-3.5" />} onClick={replay.stop}>
            Exit replay
          </Button>
        </div>
      </div>
      <div
        className="mt-3 h-1 overflow-hidden rounded-full bg-surface-3"
        role="progressbar"
        aria-label="Replay progress"
        aria-valuemin={0}
        aria-valuemax={Math.max(1, replay.total)}
        aria-valuenow={replay.cursor}
      >
        <motion.div className="h-full origin-left rounded-full bg-armoriq" initial={false} animate={{ scaleX: ratio }} transition={motionOK ? T.base : { duration: 0 }} />
      </div>
    </motion.div>
  )
}

/* ─── Cancel ─── */

export function CancelDialog({ open, onClose, onConfirm, busy }: { open: boolean; onClose: () => void; onConfirm: () => void; busy: boolean }) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      width="480px"
      title="Cancel this run?"
      description="The agent stops where it is. Anything already committed stays committed."
      dismissable={!busy}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Keep running
          </Button>
          <Button variant="danger" loading={busy} onClick={onConfirm}>
            Cancel run
          </Button>
        </div>
      }
    >
      <p className="text-sm leading-relaxed text-ink-2">Use this if the agent is doing something you do not want to wait for. You can start a new run from Workspace.</p>
    </Modal>
  )
}
