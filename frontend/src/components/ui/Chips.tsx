import type { ReactNode } from 'react'
import { FlaskConical } from 'lucide-react'
import type { Decision, DecisionSource, Layer, Outcome } from '@/api/types'
import { cn } from '@/lib/cn'
import { tint } from '@/lib/color'
import { DECISION_SOURCES, LAYERS, OUTCOMES } from '@/lib/layers'
import { Badge } from './Badge'
import { Tooltip } from './Tooltip'

export interface LayerChipProps {
  layer: Layer
  /** Show the short name. */
  compact?: boolean
  /** Replace the default label. */
  label?: ReactNode
  className?: string
}

/** A defense layer, always with its text label (colour alone never carries meaning). */
export function LayerChip({ layer, compact, label, className }: LayerChipProps) {
  const meta = LAYERS[layer]
  const Icon = meta.icon
  return (
    <Tooltip content={meta.description}>
      <span className={cn('inline-flex', className)}>
        <Badge color={meta.color} icon={<Icon />}>
          {label ?? (compact ? meta.short : meta.label)}
        </Badge>
      </span>
    </Tooltip>
  )
}

export interface OutcomeChipProps {
  outcome: Outcome
  /** Shadow decisions were evaluated only for attribution. */
  shadow?: boolean
  simulated?: boolean
  className?: string
  size?: 'sm' | 'md'
}

/** The verdict of one layer: Allowed, Blocked, Held for review, and so on. */
export function OutcomeChip({ outcome, shadow, simulated, className, size }: OutcomeChipProps) {
  const meta = OUTCOMES[outcome]
  const Icon = meta.icon
  const label = shadow ? (outcome === 'allow' ? 'Would also allow' : 'Would also block') : meta.label
  return (
    <Tooltip content={shadow ? 'Evaluated after the decisive block, only to show which other layers would also have stopped it.' : meta.description}>
      <span className={cn('inline-flex', className)}>
        <Badge color={meta.color} icon={<Icon />} dashed={shadow || simulated} size={size}>
          {label}
        </Badge>
      </span>
    </Tooltip>
  )
}

export interface SourceBadgeProps {
  source: DecisionSource
  simulated?: boolean
  className?: string
  size?: 'sm' | 'md'
}

/**
 * Exactly which component issued a decision. A simulated ArmorIQ decision gets a
 * dashed outline and an explicit SIMULATED marker: it is never presented as live.
 */
export function SourceBadge({ source, simulated, className, size }: SourceBadgeProps) {
  const meta = DECISION_SOURCES[source]
  if (!meta) return <Badge className={className}>{source}</Badge>
  const isSim = simulated || source === 'armoriq.offline_simulation'
  const Icon = isSim ? FlaskConical : meta.icon
  return (
    <Tooltip content={meta.description}>
      <span className={cn('inline-flex max-w-full flex-wrap items-center gap-1.5', className)}>
        <Badge color={meta.color} icon={<Icon />} dashed={isSim} size={size}>
          {isSim ? 'ArmorIQ (simulated)' : meta.label}
        </Badge>
        {isSim && (
          <span
            className="rounded px-1.5 py-0.5 text-[11px] font-medium"
            style={{ color: 'var(--outcome-hold)', border: '1px dashed var(--outcome-hold)', background: tint('var(--outcome-hold)', 10) }}
          >
            Simulated
          </span>
        )}
      </span>
    </Tooltip>
  )
}

/** Convenience: source badge for a Decision, honouring its simulated flag. */
export function DecisionSourceBadge({ decision, size }: { decision: Pick<Decision, 'source' | 'simulated'>; size?: 'sm' | 'md' }) {
  return <SourceBadge source={decision.source} simulated={decision.simulated} size={size} />
}
