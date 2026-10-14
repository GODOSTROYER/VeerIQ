import type { ReactNode } from 'react'
import { Bot, Database, FlaskConical, Lock, ShieldCheck } from 'lucide-react'
import type { AppState, SystemStatus } from '@/api/types'
import { plannerLabel } from '@/lib/labels'
import { ErrorState, Skeleton } from '@/components/ui'

interface Item {
  icon: ReactNode
  label: string
  value: string
  detail?: string
  /** Token reference for the status dot. */
  color: string
}

export interface StatusStripProps {
  status: SystemStatus | undefined
  statusError: Error | undefined
  onRetry: () => void
  appState: AppState | undefined
}

/** One calm row answering "is everything wired up and honest right now?" */
export function StatusStrip({ status, statusError, onRetry, appState }: StatusStripProps) {
  if (statusError && !status) return <ErrorState compact error={statusError} title="Status unavailable" onRetry={onRetry} />
  if (!status) return <Skeleton className="h-[76px] w-full rounded-2xl" />

  const sim = status.enforcement.simulated
  const readiness = status.enforcement.readiness
  const llm = status.planner.kind === 'llm'
  const items: Item[] = [
    {
      icon: sim ? <FlaskConical className="size-4" /> : <ShieldCheck className="size-4" />,
      label: 'ArmorIQ enforcement',
      value: sim ? 'Simulated' : 'Live',
      detail: sim
        ? 'Local simulation of ArmorIQ rules'
        : readiness?.state === 'verified'
          ? `Verified${status.enforcement.sdk_version ? `, SDK ${status.enforcement.sdk_version}` : ''}`
          : readiness?.state === 'failed'
            ? 'Last connection check failed'
            : status.enforcement.sdk_version
              ? `SDK ${status.enforcement.sdk_version}`
              : 'Live service',
      color: sim ? 'var(--outcome-hold)' : 'var(--layer-armoriq)',
    },
    {
      icon: <Bot className="size-4" />,
      label: 'Agent',
      value: plannerLabel(status.planner.name, status.planner.kind),
      detail: llm
        ? 'A real model plans the steps'
        : status.planner.configured_llm
          ? 'Live LLM ready; scripted by default'
          : 'Scripted re-enactment, no LLM key',
      color: 'var(--layer-grant)',
    },
    {
      icon: <Database className="size-4" />,
      label: 'PostgreSQL',
      value: status.database.ok ? 'Connected' : 'Unreachable',
      detail: `Demo data generation ${status.fixture_generation}`,
      color: status.database.ok ? 'var(--layer-postgres)' : 'var(--outcome-block)',
    },
  ]
  if (appState) {
    const ok = appState.beacon.untouched
    items.push({
      icon: <Lock className="size-4" />,
      label: 'Other tenant',
      value: ok ? 'Beacon untouched' : 'Beacon changed',
      detail: ok ? 'Checksum matches the start' : 'Checksum no longer matches',
      color: ok ? 'var(--outcome-allow)' : 'var(--outcome-block)',
    })
  }
  return (
    <section aria-label="System status" className="glass overflow-hidden rounded-2xl">
      <ul className="grid divide-line sm:grid-cols-2 sm:divide-x-0 lg:grid-flow-col lg:auto-cols-fr lg:divide-x">
        {items.map((it) => (
          <li key={it.label} className="flex items-center gap-3 border-b border-line px-5 py-3.5 last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0 lg:border-b-0">
            <span className="grid size-8 shrink-0 place-items-center rounded-lg" style={{ color: it.color, background: `color-mix(in srgb, ${it.color} 14%, transparent)` }}>
              {it.icon}
            </span>
            <span className="min-w-0 leading-tight">
              <span className="block text-xs text-ink-3">{it.label}</span>
              <span className="mt-0.5 block truncate text-sm font-semibold text-ink">{it.value}</span>
              {it.detail && <span className="block truncate text-xs text-ink-3">{it.detail}</span>}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
