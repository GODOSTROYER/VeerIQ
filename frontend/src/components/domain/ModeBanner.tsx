import { useEffect, useId, useRef, useState } from 'react'
import { Bot, FlaskConical, Info, ShieldCheck, TriangleAlert } from 'lucide-react'
import type { EnforcementReadiness, SystemStatus, SystemWarning } from '@/api/types'
import { normaliseWarnings, plannerLabel, providerLabel } from '@/lib/labels'
import { Badge, Tooltip } from '@/components/ui'

export interface ModeBannerProps {
  status: SystemStatus | undefined
}

/** Warnings worth interrupting a page for. Info-level notes live in the notes popover instead. */
function loudWarnings(status: SystemStatus): SystemWarning[] {
  return normaliseWarnings(status.warnings).filter((w) => w.level === 'warn' || w.level === 'error')
}

/**
 * Global honesty strip. When enforcement is simulated, every ArmorIQ decision in the product is
 * a local simulation, and this banner says so on every screen. Only warn/error notes get a banner;
 * expected states (scripted planner, dev cookie secret) are quiet and live in <SystemNotes>.
 */
export function ModeBanner({ status }: ModeBannerProps) {
  if (!status) return null
  const simulated = status.enforcement.simulated
  // The strip below already says enforcement is simulated; do not repeat it as a second banner.
  const warnings = loudWarnings(status).filter((w) => !(simulated && w.code === 'enforcement_simulated'))
  if (!simulated && warnings.length === 0) return null
  return (
    <div role="status" className="space-y-px">
      {simulated && (
        <div
          className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b px-4 py-1.5 text-center text-[13px]"
          style={{
            color: 'var(--outcome-hold)',
            borderColor: 'color-mix(in srgb, var(--outcome-hold) 55%, transparent)',
            background: 'color-mix(in srgb, var(--outcome-hold) 9%, var(--bg))',
          }}
        >
          <span className="inline-flex items-center gap-1.5 font-semibold">
            <FlaskConical className="size-3.5" aria-hidden />
            Simulated ArmorIQ
          </span>
          <span className="text-ink-2">
            ArmorIQ decisions are simulated locally; no live ArmorIQ call is made. Grant, domain and PostgreSQL checks are real.
          </span>
        </div>
      )}
      {warnings.map((w) => (
        <div
          key={w.code + w.message}
          className="flex items-center justify-center gap-2 border-b border-line bg-surface px-4 py-1.5 text-center text-[13px] text-ink-2"
        >
          <TriangleAlert
            className="size-3.5 shrink-0"
            style={{ color: w.level === 'error' ? 'var(--outcome-block)' : 'var(--outcome-unavailable)' }}
            aria-hidden
          />
          {w.message}
        </div>
      ))}
    </div>
  )
}

const READINESS_COPY: Record<EnforcementReadiness['state'], { label: string; hint: string }> = {
  verified: { label: 'verified', hint: 'A test plan was signed and checked against ArmorIQ policy.' },
  unverified: { label: 'not yet verified', hint: 'The ArmorIQ connection has not been probed yet. It is checked on demand.' },
  failed: { label: 'check failed', hint: 'The last probe of the ArmorIQ service failed.' },
  simulated: { label: 'simulated', hint: 'No call is made to ArmorIQ.' },
}

/** Header badge: Live ArmorIQ (with readiness) or Simulated. */
export function EnforcementBadge({ status }: { status: SystemStatus | undefined }) {
  if (!status) return <Badge tone="neutral">Checking enforcement</Badge>
  const e = status.enforcement
  if (e.simulated) {
    return (
      <Tooltip content="Decisions from ArmorIQ are simulated locally. No call is made to the ArmorIQ service.">
        <span className="inline-flex">
          <Badge tone="hold" dashed icon={<FlaskConical />}>
            Simulated
          </Badge>
        </span>
      </Tooltip>
    )
  }
  const r = e.readiness
  const copy = r ? READINESS_COPY[r.state] : null
  return (
    <Tooltip
      content={
        <span>
          Live ArmorIQ{e.sdk_version ? ` (SDK ${e.sdk_version})` : ''}. ArmorIQ signs each task&rsquo;s plan; actions outside it are refused by the ArmorIQ SDK
          locally; in-plan actions are checked by ArmorIQ policy on api.armoriq.ai. Argument checks (tenant, records) are VeerIQ&rsquo;s.
          {copy && ` Connection: ${copy.label}. ${r?.detail ?? copy.hint}`}
        </span>
      }
    >
      <span className="inline-flex">
        <Badge
          color={r?.state === 'failed' ? 'var(--outcome-unavailable)' : 'var(--layer-armoriq)'}
          icon={r?.state === 'failed' ? <TriangleAlert /> : <ShieldCheck />}
        >
          {r?.state === 'verified' ? 'Live ArmorIQ, verified' : r?.state === 'failed' ? 'ArmorIQ check failed' : 'Live ArmorIQ'}
        </Badge>
      </span>
    </Tooltip>
  )
}

/** Header badge: which planner drives the agent. A live model is colored; the scripted agent is neutral. */
export function PlannerBadge({ status }: { status: SystemStatus | undefined }) {
  if (!status) return null
  const p = status.planner
  const providers = (p.available_providers ?? []).map(providerLabel).filter(Boolean)
  const llm = p.kind === 'llm'
  return (
    <Tooltip
      content={
        llm
          ? `A real language model (${plannerLabel(p.name, p.kind)}) plans the steps. Choose it when you authorize a grant.`
          : p.configured_llm
            ? `A language model is configured${providers.length ? ` (${providers.join(', ')})` : ''}. Pick "Live LLM" when you authorize a grant; the default scenario run is a scripted re-enactment.`
            : 'No language model key is configured. The scripted agent re-enacts a fixed plan; it is not a model being fooled.'
      }
    >
      <span className="inline-flex">
        <Badge tone="neutral" color={llm ? 'var(--layer-grant)' : undefined} icon={<Bot />}>
          {llm ? `Live LLM: ${plannerLabel(p.name, p.kind)}` : p.configured_llm ? 'Scripted default, LLM ready' : plannerLabel(p.name, p.kind)}
        </Badge>
      </span>
    </Tooltip>
  )
}

/** Quiet popover listing the info-level server notes, so they do not clutter the top of every page. */
export function SystemNotes({ status }: { status: SystemStatus | undefined }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const panelId = useId()

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!status) return null
  const notes = normaliseWarnings(status.warnings).filter((w) => w.level === 'info')
  if (notes.length === 0) return null

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-[13px] text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink-2"
      >
        <Info className="size-4" aria-hidden />
        <span className="tabular">{notes.length}</span>
        <span className="sr-only">system {notes.length === 1 ? 'note' : 'notes'}</span>
      </button>
      {open && (
        <div
          id={panelId}
          role="dialog"
          aria-label="System notes"
          className="absolute right-0 top-full z-50 mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-line-strong bg-overlay p-3.5"
        >
          <p className="text-[13px] font-semibold text-ink">Good to know</p>
          <ul className="mt-2 space-y-2">
            {notes.map((n) => (
              <li key={n.code + n.message} className="flex gap-2 text-[13px] leading-snug text-ink-2">
                <Info className="mt-0.5 size-3.5 shrink-0 text-ink-3" aria-hidden />
                {n.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
