import { useId, useState, type ReactNode } from 'react'
import { Collapse } from '@/components/motion'
import { Technical } from '@/lib/detail'
import { ChevronDown, Timer } from 'lucide-react'
import type { Decision } from '@/api/types'
import { cn } from '@/lib/cn'
import { decisionHeadline, DECISION_SOURCES } from '@/lib/layers'
import { humanReason } from '@/lib/reasons'
import { invariantLabel } from '@/lib/labels'
import { Digest, KeyValue, KeyValueGrid, OutcomeChip, SourceBadge } from '@/components/ui'

export interface DecisionCardProps {
  decision: Decision
  /** Optional tool context for a plain-language reason. */
  tool?: string
  /** Start with the technical details open. */
  defaultOpen?: boolean
  className?: string
  /** Extra content under the reason (e.g. a handler-entries counter). */
  footer?: ReactNode
}

/**
 * One layer's verdict in plain language: who decided, what they decided, why.
 * Technical evidence (including ArmorIQ's sanitized response) sits behind "Technical details".
 */
export function DecisionCard({ decision, tool, defaultOpen = false, className, footer }: DecisionCardProps) {
  const detailId = useId()
  const [open, setOpen] = useState(defaultOpen)
  const meta = DECISION_SOURCES[decision.source]
  const sponsor = decision.sponsor
  const evidenceKeys = Object.keys(decision.evidence ?? {})

  return (
    <article
      className={cn('relative overflow-hidden rounded-xl border', decision.shadow && 'border-dashed', className)}
      style={{
        borderColor: 'var(--border)',
        background: 'var(--bg-raised)',
      }}
    >
      <div className="py-3 pl-5 pr-4">
        <div className="flex flex-wrap items-center gap-2">
          <OutcomeChip outcome={decision.outcome} shadow={decision.shadow} simulated={decision.simulated} />
          <Technical inline><SourceBadge source={decision.source} simulated={decision.simulated} /></Technical>
          <Technical inline>{decision.latency_ms !== null && decision.latency_ms !== undefined && (
            <span className="ml-auto inline-flex items-center gap-1 text-xs text-ink-3">
              <Timer className="size-3" aria-hidden />
              <span className="tabular">{Math.round(decision.latency_ms)} ms</span>
            </span>
          )}</Technical>
        </div>
        <p className="mt-2 text-sm font-medium text-ink">{decisionHeadline(decision)}</p>
        <p className="mt-1 text-[13px] leading-snug text-ink-2">{humanReason(decision, tool)}</p>
        {decision.simulated && (
          <p className="mt-2 text-xs text-ink-3">{meta?.description}</p>
        )}
        {footer && <div className="mt-2">{footer}</div>}

        {(
          <>
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              aria-controls={detailId}
              className="mt-2.5 inline-flex items-center gap-1 rounded-md px-1 py-1 text-xs font-medium text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink active:bg-surface-3"
            >
              <ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} aria-hidden />
              Technical details
            </button>
            <Collapse open={open} id={detailId}>
                  <div className="mt-3 space-y-3 border-t border-line pt-3">
                    <KeyValueGrid columns={2}>
                      <KeyValue label="Raw reason">{decision.reason || 'No reason recorded'}</KeyValue>
                      {decision.invariant && (
                        <KeyValue label="Rule" hint={decision.invariant}>
                          {invariantLabel(decision.invariant)}
                        </KeyValue>
                      )}
                      <KeyValue label="Decided by" mono>
                        {decision.source}
                      </KeyValue>
                      {sponsor && (
                        <>
                          <KeyValue label="ArmorIQ mode">{sponsor.mode === 'live' ? 'Live service' : 'Offline simulation'}</KeyValue>
                          {sponsor.session_mode && <KeyValue label="Session mode">{sponsor.session_mode}</KeyValue>}
                          {sponsor.sdk_version && <KeyValue label="SDK version" mono>{sponsor.sdk_version}</KeyValue>}
                          {sponsor.raw_action && <KeyValue label="Enforcement action" mono>{sponsor.raw_action}</KeyValue>}
                          {sponsor.matched_policy && <KeyValue label="Matched policy">{sponsor.matched_policy}</KeyValue>}
                          {sponsor.delegation_id && <KeyValue label="Delegation" mono>{sponsor.delegation_id}</KeyValue>}
                          {sponsor.plan_id && <KeyValue label="Plan" mono>{sponsor.plan_id}</KeyValue>}
                          {sponsor.plan_hash && (
                            <KeyValue label="Plan hash">
                              <Digest value={sponsor.plan_hash} label="plan hash" />
                            </KeyValue>
                          )}
                        </>
                      )}
                    </KeyValueGrid>
                    {!sponsor && evidenceKeys.length === 0 && <p className="text-xs text-ink-3">No additional evidence was recorded for this decision.</p>}
                    {sponsor && Object.keys(sponsor.sanitized_response ?? {}).length > 0 && (
                      <JsonBlock label="ArmorIQ response (sanitized)" value={sponsor.sanitized_response} />
                    )}
                    {evidenceKeys.length > 0 && <JsonBlock label="Evidence" value={decision.evidence} />}
                  </div>
            </Collapse>
          </>
        )}
      </div>
    </article>
  )
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <p className="mb-1 text-xs text-ink-3">{label}</p>
      <pre className="max-h-56 overflow-auto rounded-xl bg-sunken p-3 font-mono text-[12px] leading-relaxed text-ink-2">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}
