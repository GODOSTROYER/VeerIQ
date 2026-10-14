import { Fragment } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { Check, Minus } from 'lucide-react'
import type { Decision, Layer } from '@/api/types'
import { Technical } from '@/lib/detail'
import { T } from '@/lib/motion'
import { cn } from '@/lib/cn'
import { tint } from '@/lib/color'
import { DEFENSE_LAYERS, LAYERS, OUTCOMES, sourceLabel } from '@/lib/layers'

export interface DefenseStackProps {
  /** All decisions recorded for ONE proposal (decisive, allowed and shadow). */
  decisions: Decision[]
  /** Hide the reason text under the decisive layer. */
  compact?: boolean
  /** Replay the entrance animation when this key changes (e.g. the selected proposal id). */
  animateKey?: string
  className?: string
}

type LayerState =
  | { kind: 'untouched' }
  | { kind: 'allowed'; decision: Decision }
  | { kind: 'stopped'; decision: Decision; shadows: Decision[] }
  | { kind: 'shadow'; decisions: Decision[] }

function stateFor(layer: Layer, decisions: Decision[]): LayerState {
  const here = decisions.filter((d) => d.layer === layer)
  if (here.length === 0) return { kind: 'untouched' }
  const stopper = here.find((d) => !d.shadow && d.outcome !== 'allow' && d.outcome !== 'skipped')
  if (stopper) return { kind: 'stopped', decision: stopper, shadows: here.filter((d) => d.shadow) }
  const shadows = here.filter((d) => d.shadow && d.outcome !== 'allow')
  const allowed = here.find((d) => !d.shadow && d.outcome === 'allow')
  if (allowed) return { kind: 'allowed', decision: allowed }
  if (shadows.length) return { kind: 'shadow', decisions: shadows }
  return { kind: 'untouched' }
}

/**
 * The five defense layers as a vertical stack, outermost first. It answers one
 * question at a glance: which layer stopped this action? The deciding layer glows
 * and says "Stopped here"; layers that allowed it show a check; layers that would
 * also have blocked it are marked as such; layers never reached are dimmed.
 */
export function DefenseStack({ decisions, compact, animateKey, className }: DefenseStackProps) {
  const reduce = useReducedMotion()
  const runtimeBlock = decisions.find((d) => d.layer === 'runtime' && !d.shadow && d.outcome !== 'allow')
  const layers: Layer[] = runtimeBlock ? ['runtime', ...DEFENSE_LAYERS] : [...DEFENSE_LAYERS]
  const states = layers.map((l) => [l, stateFor(l, decisions)] as const)
  const stopped = states.find(([, s]) => s.kind === 'stopped')
  const anyDecision = decisions.length > 0
  const passedAll = anyDecision && !stopped

  return (
    <div className={cn('relative', className)} role="list" aria-label="Defense layers for this action">
      {states.map(([layer, state], i) => {
        const meta = LAYERS[layer]
        const Icon = meta.icon
        const isStopped = state.kind === 'stopped'
        const dim = state.kind === 'untouched'
        const decision = state.kind === 'stopped' ? state.decision : state.kind === 'allowed' ? state.decision : undefined
        const outcome = decision ? OUTCOMES[decision.outcome] : undefined
        const shadowCount = state.kind === 'shadow' ? state.decisions.length : state.kind === 'stopped' ? state.shadows.length : 0
        const stopColor = isStopped && outcome ? outcome.color : meta.color

        return (
          <Fragment key={layer}>
            {i > 0 && (
              <div aria-hidden className="ml-[21px] h-3 w-px" style={{ background: dim ? 'var(--border)' : tint(meta.color, 45) }} />
            )}
            <motion.div
              role="listitem"
              key={`${animateKey}-${layer}`}
              initial={reduce ? false : { opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ ...T.fast, delay: reduce ? 0 : i * 0.035 }}
              className={cn('relative flex items-start gap-3 rounded-xl border px-3 py-2.5', state.kind === 'shadow' && 'border-dashed')}
              style={{
                borderColor: isStopped ? tint(stopColor, 70) : state.kind === 'allowed' ? tint(meta.color, 28) : 'var(--border)',
                background: isStopped ? tint(stopColor, 12) : 'var(--surface)',
              }}
            >
              <span
                className="grid size-9 shrink-0 place-items-center rounded-lg"
                style={{ color: meta.color, background: tint(meta.color, isStopped ? 24 : 14) }}
              >
                <Icon className="size-[18px]" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-sm font-semibold text-ink">{meta.label}</span>
                  {decision && (
                    <Technical inline><span className="truncate text-xs text-ink-3">
                      {sourceLabel(decision)}
                    </span></Technical>
                  )}
                </div>
                {isStopped && decision && outcome && (
                  <>
                    <p className="mt-0.5 text-[13px] font-semibold" style={{ color: stopColor }}>
                      {decision.outcome === 'block'
                        ? 'Stopped here'
                        : decision.outcome === 'hold'
                          ? 'Held here for a reviewer'
                          : decision.outcome === 'unavailable'
                            ? 'Could not be checked, so it failed closed'
                            : `${outcome.label} here`}
                    </p>
                    {!compact && <p className="mt-1 text-[13px] leading-snug text-ink-2">{decision.reason}</p>}
                  </>
                )}
                {state.kind === 'allowed' && <p className="mt-0.5 text-xs text-ink-3">Passed this layer</p>}
                {state.kind === 'shadow' && (
                  <p className="mt-0.5 text-xs text-ink-2">Would also block this action</p>
                )}
                {isStopped && shadowCount > 0 && <p className="mt-1 text-xs text-ink-3">Also checked afterwards: would block too</p>}
                {state.kind === 'untouched' && <p className="mt-0.5 text-xs text-ink-3">{anyDecision ? 'Never reached' : 'Waiting'}</p>}
              </div>
              <span className="mt-0.5 shrink-0">
                {state.kind === 'allowed' ? (
                  <span className="grid size-6 place-items-center rounded-full" style={{ color: 'var(--outcome-allow)', background: tint('var(--outcome-allow)', 14) }}>
                    <Check className="size-3.5" aria-label="Passed" />
                  </span>
                ) : state.kind === 'shadow' ? (
                  <span
                    className="rounded-full border border-dashed px-2 py-0.5 text-[11px] font-medium"
                    style={{ color: 'var(--outcome-block)', borderColor: tint('var(--outcome-block)', 55) }}
                  >
                    Would also block
                  </span>
                ) : state.kind === 'untouched' ? (
                  <Minus className="size-4 text-ink-3" aria-hidden />
                ) : null}
              </span>
            </motion.div>
          </Fragment>
        )
      })}
      {passedAll && (
        <p className="mt-3 flex items-center gap-2 text-[13px] text-ink-2">
          <span className="size-1.5 rounded-full" style={{ background: 'var(--outcome-allow)' }} aria-hidden />
          Passed every layer it reached.
        </p>
      )}
    </div>
  )
}
