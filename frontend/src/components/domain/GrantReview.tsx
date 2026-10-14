import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, CircleAlert, FileText, Lock, Play, Sparkles } from 'lucide-react'
import { api, errorMessage } from '@/api/client'
import { invalidate, TAGS } from '@/api/bus'
import { useSession } from '@/api/session'
import type { Run, RunPlannerChoice, ScenarioSpec, SystemStatus, TaskGrant } from '@/api/types'
import { cn } from '@/lib/cn'
import { tint } from '@/lib/color'
import { PLANNER_CHOICES, plannerLabel } from '@/lib/labels'
import { Button, HoldToConfirmButton, Modal, Skeleton } from '@/components/ui'
import { GrantSummary } from './GrantSummary'

export interface GrantReviewProps {
  open: boolean
  onClose: () => void
  /** The draft grant returned by POST /grants/draft. */
  grant: TaskGrant | null
  scenario?: ScenarioSpec | null
  status?: SystemStatus
  /** Override the default navigation to /runs/:id after the run starts. */
  onStarted?: (run: Run) => void
}

type Phase = 'idle' | 'authorizing' | 'starting'

const ICONS = { auto: Sparkles, scripted: FileText, llm: Bot } as const

/**
 * The exact authority the agent is about to receive, in plain language, plus the planner choice.
 * Authorizing is deliberate: the button must be held. Then: authorize the grant, start the run, open its workspace.
 */
export function GrantReview({ open, onClose, grant, scenario, status, onStarted }: GrantReviewProps) {
  const navigate = useNavigate()
  const { identity } = useSession()
  const [planner, setPlanner] = useState<RunPlannerChoice>('auto')
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [authorized, setAuthorized] = useState(false)

  const llmReady = status?.planner.configured_llm ?? false
  const harness = scenario?.default_planner === 'harness'
  const simulated = status?.enforcement.simulated ?? false
  const grantId = grant?.grant_id

  // Reset for every new draft.
  useEffect(() => {
    setError(null)
    setPhase('idle')
    setAuthorized(grant?.status === 'active')
    const d = scenario?.default_planner
    setPlanner(d === 'scripted' ? 'scripted' : (d === 'llm' || scenario?.kind === 'flagship') && llmReady ? 'llm' : 'auto')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grantId])

  const isPrincipal = !!grant && identity?.identity_id === grant.principal
  const canAuthorize = !!grant && !!identity && identity.role === 'operator' && isPrincipal

  const start = async () => {
    if (!grant) return
    setError(null)
    try {
      if (!authorized && grant.status !== 'active') {
        setPhase('authorizing')
        await api.post<TaskGrant>(`/grants/${grant.grant_id}/authorize`)
        setAuthorized(true)
      }
      setPhase('starting')
      const run = await api.post<Run>('/runs', { grant_id: grant.grant_id, planner: harness ? 'auto' : planner })
      invalidate(TAGS.runs)
      onClose()
      if (onStarted) onStarted(run)
      else navigate(`/runs/${run.run_id}`)
    } catch (err) {
      setError(errorMessage(err))
      setPhase('idle')
    }
  }

  const busy = phase !== 'idle'

  return (
    <Modal
      open={open}
      onClose={onClose}
      dismissable={!busy}
      width="760px"
      title={scenario ? `Authorize ${scenario.title}` : 'Review the grant'}
      description="Review what the agent may do. Hold to authorize the grant, then follow the run."
      footer={
        <div className="flex flex-col-reverse items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            {!canAuthorize && grant && (
              <span className="inline-flex items-center gap-1.5 text-[13px] text-ink-3">
                <Lock className="size-3.5" aria-hidden />
                {identity?.role !== 'operator' ? 'Only an operator can authorize.' : 'Only the grant’s owner can authorize it.'}
              </span>
            )}
          </div>
          <HoldToConfirmButton
            key={grantId}
            onConfirm={start}
            loading={busy}
            disabled={!canAuthorize}
            icon={<Play />}
            holdLabel={phase === 'authorizing' ? 'Authorizing' : 'Keep holding — grant ready'}
            hint="Press and hold to authorize this grant and start the agent"
          >
            {phase === 'authorizing' ? 'Authorizing' : phase === 'starting' ? 'Starting the agent' : 'Hold to authorize & start'}
          </HoldToConfirmButton>
        </div>
      }
    >
      {!grant ? (
        <div role="status" aria-label="Preparing the grant" className="space-y-4"><Skeleton className="h-16 w-full" /><Skeleton className="h-20 w-full" /><Skeleton className="h-24 w-full" /></div>
      ) : (
        <div className="space-y-5">
          <GrantSummary grant={grant} variant="full" simulated={simulated} />

          <section aria-labelledby="planner-heading">
            <h3 id="planner-heading" className="text-sm font-semibold text-ink">
              Who plans the steps
            </h3>
            <p className="mt-0.5 text-xs text-ink-3">The planner chooses the order of actions. It cannot widen the grant above, whichever you pick.</p>
            {harness ? (
              <p className="mt-3 rounded-xl border border-line bg-raised px-3.5 py-3 text-[13px] leading-snug text-ink-2">
                This scenario runs a fixed set of boundary probes through the real checks, so there is no planner to choose.
              </p>
            ) : (
              <div role="radiogroup" aria-labelledby="planner-heading" className="mt-3 divide-y divide-line rounded-xl border border-line">
                {(Object.keys(PLANNER_CHOICES) as RunPlannerChoice[]).map((key) => {
                  const choice = PLANNER_CHOICES[key]
                  const Icon = ICONS[key]
                  const disabled = key === 'llm' && !llmReady
                  const selected = planner === key
                  return (
                    <button
                      key={key}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      disabled={disabled || busy}
                      onClick={() => setPlanner(key)}
                      className={cn(
                        'flex w-full flex-col items-start gap-1 px-3.5 py-3 text-left transition-colors active:bg-surface-3 disabled:cursor-not-allowed',
                        disabled ? 'opacity-50' : 'hover:bg-surface-2',
                      )}
                      style={{

                        background: selected ? tint('var(--layer-armoriq)', 12) : 'var(--surface)',
                      }}
                    >
                      <span className="flex items-center gap-2 text-sm font-medium text-ink">
                        <Icon className="size-4" aria-hidden />
                        {choice.label}
                      </span>
                      <span className="text-xs leading-snug text-ink-3">
                        {disabled
                          ? 'No language model key is set on the server, so only the scripted agent is available.'
                          : key === 'auto' && status
                            ? `Uses ${plannerLabel(status.planner.name, status.planner.kind)}`
                            : key === 'llm' && status?.planner.kind === 'llm'
                              ? `A real model plans the steps: ${plannerLabel(status.planner.name, status.planner.kind)}`
                              : key === 'scripted'
                                ? 'A deterministic re-enactment. No model is involved.'
                                : choice.hint}
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
          </section>

          {error && (
            <div
              role="alert"
              className="flex items-start gap-2.5 rounded-xl border px-3.5 py-3 text-[13px] leading-snug"
              style={{ color: 'var(--outcome-block)', borderColor: tint('var(--outcome-block)', 45), background: tint('var(--outcome-block)', 10) }}
            >
              <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span className="text-ink">
                {error} {authorized && 'The grant is already authorized; holding the button again will only start the run.'}
              </span>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
