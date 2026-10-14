import { useMemo } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import type { AppState, SnapshotDiffRow } from '@/api/types'
import { cn } from '@/lib/cn'
import { formatDateTime, pluralize } from '@/lib/format'

type Kind = 'snapshot' | 'damage' | 'decision' | 'detect' | 'now'

interface RibbonEvent {
  id: string
  at: string
  kind: Kind
  label: string
}

const KIND_COLOR: Record<Kind, string> = {
  snapshot: 'var(--text)',
  damage: 'var(--diff-bad)',
  decision: 'var(--diff-keep)',
  detect: 'var(--text-3)',
  now: 'var(--text)',
}

/** Build the story of the incident from real timestamps in the application state: no event is invented. */
export function buildRibbonEvents(state: AppState, rows: SnapshotDiffRow[]): RibbonEvent[] {
  const events: RibbonEvent[] = [
    { id: 'snapshot', at: state.snapshot.taken_at, kind: 'snapshot', label: 'Snapshot taken' },
    { id: 'damage', at: state.incident.started_at, kind: 'damage', label: 'Damage begins' },
    { id: 'detected', at: state.incident.detected_at, kind: 'detect', label: 'Incident detected' },
  ]
  for (const g of state.access_grants) {
    if (g.status === 'revoked' && g.revoked_at) {
      events.push({ id: `revoked-${g.grant_id}`, at: g.revoked_at, kind: 'decision', label: `${g.principal} access revoked` })
    }
  }
  const customers = state.deleted.filter((d) => d.entity_type === 'customer')
  for (const d of customers.length ? customers : state.deleted) {
    events.push({ id: `deleted-${d.entity_id}`, at: d.deleted_at, kind: 'decision', label: `${d.display_name} deleted` })
  }
  for (const row of rows) {
    if (row.condition !== 'changed_after_snapshot') continue
    const order = state.orders.find((o) => o.order_id === row.order_id)
    if (order) events.push({ id: `later-${row.order_id}`, at: order.updated_at, kind: 'decision', label: `Order ${row.order_id} ${order.status}` })
  }
  events.sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime())
  events.push({ id: 'now', at: new Date().toISOString(), kind: 'now', label: 'Now' })
  return events
}

export interface TimeRibbonProps {
  state: AppState
  rows: SnapshotDiffRow[]
  className?: string
}

/**
 * The whole product idea on one line. Everything between the snapshot and now is shown in order:
 * red is damage the agent repairs, blue is a decision made since the snapshot that must survive.
 */
export function TimeRibbon({ state, rows, className }: TimeRibbonProps) {
  const reduce = useReducedMotion()
  const events = useMemo(() => buildRibbonEvents(state, rows), [state, rows])
  const kept = events.filter((e) => e.kind === 'decision').length
  const n = events.length

  return (
    <div className={cn('flex h-full flex-col', className)}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-ink-2">
        <Legend color="var(--diff-bad)" label="Damage to repair" />
        <Legend color="var(--diff-keep)" label="Decisions to keep" />
      </div>

      <div className="mt-6 overflow-x-auto pb-1">
        <ol className="relative grid min-w-[620px]" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
          <span aria-hidden className="absolute top-[5px] h-px" style={{ left: `${50 / n}%`, right: `${50 / n}%`, background: 'var(--border-strong)' }} />
          <motion.span
            aria-hidden
            className="absolute top-[4px] h-[3px] origin-left rounded-full"
            style={{
              left: `${50 / n}%`,
              right: `${50 / n}%`,
              background: 'linear-gradient(90deg, var(--text-3), var(--diff-bad) 28%, var(--diff-keep) 62%, var(--text))',
              opacity: 0.55,
            }}
            initial={reduce ? false : { scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1], delay: 0.2 }}
          />
          {events.map((e, i) => (
            <motion.li
              key={e.id}
              className="relative flex flex-col items-center px-1 text-center"
              initial={reduce ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: reduce ? 0 : 0.3 + i * 0.09, duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
            >
              <span
                aria-hidden
                className={cn('relative z-10 block size-[11px] rounded-full border-2', e.kind === 'now' && 'pulse-dot')}
                style={{
                  background: e.kind === 'snapshot' || e.kind === 'now' ? KIND_COLOR[e.kind] : 'var(--bg)',
                  borderColor: KIND_COLOR[e.kind],
                  color: KIND_COLOR[e.kind],
                }}
              />
              <span className="mt-3 text-[13px] font-medium leading-tight text-ink">{e.label}</span>
              <span className="mt-1 text-[11px] leading-tight text-ink-3">
                {e.kind === 'now' ? 'Today' : formatDateTime(e.at).replace(' UTC', '')}
              </span>
            </motion.li>
          ))}
        </ol>
      </div>

      <p className="mt-auto pt-6 text-[13px] leading-relaxed text-ink-2">
        Restoring everything to the snapshot would also undo {kept === 0 ? 'later changes' : pluralize(kept, 'decision')} made since. VeerIQ repairs only the
        damaged fields.
      </p>
    </div>
  )
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden className="size-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  )
}
