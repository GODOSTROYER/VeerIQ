import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Collapse } from '@/components/motion'
import { useMotionOK } from '@/lib/motion'
import { ArrowRight, Building2, Check, Gavel, ShieldAlert, ShieldCheck, Undo2 } from 'lucide-react'
import { errorMessage } from '@/api/client'
import { useApprovals } from '@/api/hooks'
import { useSession } from '@/api/session'
import { TERMINAL_RUN_STATUSES, type Run, type ScenarioSpec } from '@/api/types'
import { cn } from '@/lib/cn'
import { tint } from '@/lib/color'
import { tenantName } from '@/lib/labels'
import { APPROVER_ID, OPERATOR_ID, OTHER_TENANT_ID, perspective } from '@/lib/roles'
import { Button, ErrorState, RunStatusPill, Skeleton, useToast } from '@/components/ui'

const SEEN_KEY = 'rewindsafe.tour.seen'

function readSeen(): string[] {
  try {
    return JSON.parse(localStorage.getItem(SEEN_KEY) ?? '[]') as string[]
  } catch {
    return []
  }
}
function markSeen(step: string) {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify([...new Set([...readSeen(), step])]))
  } catch {
    /* storage unavailable: the step just won't show as done */
  }
}

export interface GuidedTourProps {
  scenarios: ScenarioSpec[] | undefined
  runs: Run[] | undefined
  launchingId: string | null
  onLaunch: (s: ScenarioSpec) => void
  error?: Error
  onRetry?: () => void
}

interface Step {
  id: string
  icon: ReactNode
  color: string
  title: string
  why: string
  expect: string
  done: boolean
  status?: ReactNode
  action: ReactNode
}

/**
 * The central "start here" dashboard: four things to try, each with its purpose and the
 * outcome to expect, and one button that switches perspective for you when a step needs it.
 */
export function GuidedTour({ scenarios, runs, launchingId, onLaunch, error, onRetry }: GuidedTourProps) {
  const { identity, signIn } = useSession()
  const navigate = useNavigate()
  const toast = useToast()
  const reduce = !useMotionOK()
  const pending = useApprovals('pending')
  const [switching, setSwitching] = useState<string | null>(null)
  const [seen, setSeen] = useState(readSeen)
  const [selected, setSelected] = useState<string | null>(null)

  if (!identity) return null

  const as = async (identityId: string, key: string, then: () => void) => {
    if (identity.identity_id === identityId) return then()
    setSwitching(key)
    try {
      await signIn(identityId)
      then()
    } catch (err) {
      toast.error('Could not switch perspective', errorMessage(err))
    } finally {
      setSwitching(null)
    }
  }
  const see = (id: string) => {
    markSeen(id)
    setSeen(readSeen())
  }

  // Viewing as the other tenant: the whole point is that Atlas's data is gone.
  if (identity.identity_id === OTHER_TENANT_ID || identity.tenant_id !== 'atlas') {
    return (
      <section aria-labelledby="tour-title" className="glass rounded-2xl p-5 sm:p-6" style={{ borderColor: tint(identity.color, 45) }}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl">
            <h2 id="tour-title" className="text-xl font-semibold tracking-[-0.02em] text-ink">
              You are now {tenantName(identity.tenant_id)}, a different company on the same system
            </h2>
            <p className="mt-2 text-[14px] leading-relaxed text-ink-2">
              Look around: none of Atlas&rsquo;s orders, runs or approvals appear here, and an Atlas run link returns &ldquo;not found&rdquo;. The server scopes every query
              to the signed-in tenant. This is the tenant-isolation step of the tour.
            </p>
          </div>
          <Button
            variant="primary"
            icon={<Undo2 className="size-4" />}
            loading={switching === 'back'}
            onClick={() => void as(OPERATOR_ID, 'back', () => undefined)}
          >
            Back to the tour
          </Button>
        </div>
      </section>
    )
  }

  const find = (id: string) => scenarios?.find((s) => s.scenario_id === id)
  const latestOf = (id: string) => runs?.find((r) => r.scenario_id === id)
  const poisoned = find('poisoned')
  const review = find('review')
  const poisonedRun = latestOf('poisoned')
  const reviewRun = latestOf('review')
  const waiting = pending.data?.length ?? 0
  // A step counts as done once a run finished and showed its outcome; cancelled or crashed runs don't.
  const finished = (r: Run | undefined) => !!r && TERMINAL_RUN_STATUSES.includes(r.status) && r.status !== 'cancelled' && r.status !== 'failed'

  const runLink = (r: Run | undefined) =>
    r ? (
      <span className="flex flex-wrap items-center gap-2">
        <RunStatusPill status={r.status} />
        <Link to={`/runs/${r.run_id}`} className="inline-flex items-center gap-1 text-[13px] font-medium text-ink underline-offset-4 hover:underline">
          Open run <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      </span>
    ) : null

  const launchAsOperator = (s: ScenarioSpec | undefined, key: string) => s && void as(OPERATOR_ID, key, () => onLaunch(s))

  const steps: Step[] = [
    {
      id: 'poisoned',
      icon: <ShieldAlert className="size-4" />,
      color: 'var(--layer-armoriq)',
      title: 'Stop a hostile recovery instruction',
      why: 'A note planted in the backup tells the recovery agent to re-enable a revoked admin account and to edit another company’s order.',
      expect: 'ArmorIQ refuses the off-plan admin call, the grant refuses the other company’s order, and the agent still repairs the 2 damaged orders in one commit.',
      done: finished(poisonedRun),
      status: runLink(poisonedRun),
      action: (
        <Button
          variant={finished(poisonedRun) ? 'secondary' : 'primary'}
          size="sm"
          icon={<ShieldAlert className="size-3.5" />}
          loading={switching === 'poisoned' || launchingId === 'poisoned'}
          disabled={!poisoned || launchingId !== null}
          onClick={() => launchAsOperator(poisoned, 'poisoned')}
        >
          {poisonedRun ? 'Run it again' : 'Run it'}
        </Button>
      ),
    },
    {
      id: 'review',
      icon: <Gavel className="size-4" />,
      color: 'var(--layer-approval)',
      title: 'Require a second person for big money',
      why: 'A repair worth more than $5,000 should not be committed on one person’s say-so, least of all an AI agent’s.',
      expect:
        waiting > 0
          ? 'The run is paused, waiting for a decision. Switch to the Approver to approve or reject it; the operator who started it is not allowed to.'
          : 'The run pauses before committing. You then switch to the Approver to decide; the operator who started it cannot approve their own run.',
      done: finished(reviewRun),
      status: runLink(reviewRun),
      action:
        waiting > 0 ? (
          <Button
            variant="primary"
            size="sm"
            icon={<Gavel className="size-3.5" />}
            loading={switching === 'approve'}
            onClick={() => void as(APPROVER_ID, 'approve', () => navigate('/approvals'))}
          >
            {identity.identity_id === APPROVER_ID ? 'Decide now' : 'Switch to Approver and decide'}
          </Button>
        ) : (
          <Button
            variant={finished(reviewRun) ? 'secondary' : 'primary'}
            size="sm"
            icon={<Gavel className="size-3.5" />}
            loading={switching === 'review' || launchingId === 'review'}
            disabled={!review || launchingId !== null}
            onClick={() => launchAsOperator(review, 'review')}
          >
            {reviewRun ? 'Run it again' : 'Start it'}
          </Button>
        ),
    },
    {
      id: 'isolation',
      icon: <Building2 className="size-4" />,
      color: 'var(--layer-grant)',
      title: 'Check that companies can’t see each other',
      why: 'Beacon Coffee Co. runs on the same system as Atlas Outfitters. Recovery must never leak or touch across that line.',
      expect: 'As Beacon you see only Beacon’s data: none of Atlas’s orders, runs or approvals.',
      done: seen.includes('isolation'),
      action: (
        <Button
          variant={seen.includes('isolation') ? 'secondary' : 'primary'}
          size="sm"
          icon={<Building2 className="size-3.5" />}
          loading={switching === 'isolation'}
          onClick={() => {
            see('isolation')
            void as(OTHER_TENANT_ID, 'isolation', () => window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' }))
          }}
        >
          View as {perspective({ identity_id: OTHER_TENANT_ID, role: 'operator' }).label.toLowerCase()}
        </Button>
      ),
    },
    {
      id: 'proof',
      icon: <ShieldCheck className="size-4" />,
      color: 'var(--outcome-allow)',
      title: 'See the proof',
      why: 'Claims are cheap. Every refusal is recorded with the layer that made it and the signed plan it was checked against.',
      expect: 'Live ArmorIQ decisions, what each defense layer guarantees, and a one-click verification suite you can run yourself.',
      done: seen.includes('proof'),
      action: (
        <Button
          variant={seen.includes('proof') ? 'secondary' : 'primary'}
          size="sm"
          iconRight={<ArrowRight className="size-3.5" />}
          onClick={() => {
            see('proof')
            navigate('/proof')
          }}
        >
          Open the proof board
        </Button>
      ),
    },
  ]

  const doneCount = steps.filter((s) => s.done).length

  const current = selected ?? steps.find(s => !s.done)?.id ?? steps[0].id
  const active = steps.find(s => s.id === current) ?? steps[0]
  return (
    <section aria-labelledby="tour-title">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div><h2 id="tour-title" className="text-xl font-semibold tracking-[-0.025em] text-ink">Four things to try</h2><p className="mt-1 text-sm text-ink-3">About 3 minutes. We switch perspective when a step needs it.</p></div>
        <div className="flex items-center gap-3"><span className="text-xs tabular text-ink-3">{doneCount} of 4 done</span><div className="h-1 w-24 overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-label="Tour completion" aria-valuemin={0} aria-valuemax={4} aria-valuenow={doneCount}><div className="h-full origin-left bg-[var(--outcome-allow)] transition-transform duration-200 motion-reduce:transition-none" style={{ transform: `scaleX(${doneCount / 4})` }} /></div></div>
      </div>
      {error && (!scenarios || !runs) ? <ErrorState compact error={error} title="The tour did not load" onRetry={onRetry} /> : !scenarios || !runs ? <div className="space-y-3" role="status" aria-label="Loading guided tour"><Skeleton className="h-14 w-full" /><Skeleton className="h-32 w-full" /></div> : <div className="overflow-hidden rounded-2xl border border-line bg-raised">
        <ol className="grid grid-cols-2 gap-px bg-line lg:grid-cols-4" aria-label="Choose a tour step">
          {steps.map((s, idx) => <li key={s.id} className="bg-raised"><button type="button" onClick={() => setSelected(s.id)} aria-current={s.id === current ? 'step' : undefined} aria-expanded={s.id === current} aria-controls={`tour-${s.id}`} className={cn('flex h-full w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-2 active:bg-surface-3', s.id === current && 'bg-surface-2')}>
            <span className="grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold" style={s.done ? { background: 'var(--outcome-allow)', color: 'var(--text-inverse)' } : { background: tint(s.color, 18), color: s.color }}>{s.done ? <Check className="size-4" aria-label="Done" /> : idx + 1}</span>
            <span className="text-[13px] font-medium text-ink">{['Stop the trap', 'Require a reviewer', 'Check tenant isolation', 'See the proof'][idx]}{s.id === current && <span className="mt-0.5 block text-xs text-ink-3">Current step</span>}</span>
          </button></li>)}
        </ol>
        {steps.map(s => <Collapse key={s.id} open={s.id === active.id}><div id={`tour-${s.id}`} className="border-t border-line p-4 sm:p-5">
          <h3 className="text-base font-semibold text-ink">{s.title}</h3>
          <div className="mt-3 grid gap-4 md:grid-cols-[1fr_1.3fr_auto]">
            <div><p className="text-xs font-medium text-ink-3">Why it matters</p><p className="mt-1 text-[13px] leading-relaxed text-ink-2">{s.why}</p></div>
            <div><p className="text-xs font-medium text-ink-3">What you’ll see</p><p className="mt-1 text-[13px] leading-relaxed text-ink-2">{s.expect}</p></div>
            <div className="flex flex-col items-start justify-center gap-3 md:max-w-56">{s.status}{s.action}</div>
          </div>
        </div></Collapse>)}
      </div>}
      {pending.error && !pending.data && <ErrorState compact error={pending.error} title="Pending approvals could not be checked" onRetry={() => void pending.refetch()} />}
    </section>
  )
}
