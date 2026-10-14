import type { ReactNode } from 'react'
import { ArrowRight } from 'lucide-react'
import type { SnapshotDiffRow, SnapshotOrderValues } from '@/api/types'
import { cn } from '@/lib/cn'
import { formatMoney } from '@/lib/format'
import { CONDITION, fieldLabel } from '@/lib/labels'
import { Badge } from '@/components/ui'

export interface OrderDiffTableProps {
  rows: SnapshotDiffRow[]
  /** Order ids repaired by VeerIQ: their damaged cells morph red to green. */
  repairedIds?: readonly string[]
  /** Values after a repair (from a receipt or the live state), keyed by order id. Overrides the snapshot as the "after" value. */
  after?: Record<string, SnapshotOrderValues | null | undefined>
  /** Order ids that belong to another tenant (shown sealed, never as repairable). */
  foreignOrderIds?: readonly string[]
  /** Order ids the agent is currently targeting; shown with a left accent. */
  targetIds?: readonly string[]
  onRowClick?: (row: SnapshotDiffRow) => void
  /** Tighter rows for side panels. */
  compact?: boolean
  emptyState?: ReactNode
  className?: string
}

type Field = 'total_cents' | 'shipping_region' | 'status'
const FIELDS: Field[] = ['total_cents', 'shipping_region', 'status']

function render(field: Field, v: SnapshotOrderValues | null | undefined): string {
  if (!v) return 'Deleted'
  if (field === 'total_cents') return formatMoney(v.total_cents)
  const raw = v[field]
  if (raw === null || raw === undefined || raw === '') return 'None'
  return field === 'status' ? String(raw).charAt(0).toUpperCase() + String(raw).slice(1) : String(raw)
}

/**
 * The incident at a glance: for each order, what the snapshot said, what is true now, and what the repair
 * produced. Damaged cells show the bad value over the snapshot value; repaired cells morph red to green;
 * later legitimate edits and deletions are labelled so nobody mistakes them for damage.
 */
export function OrderDiffTable({ rows, repairedIds = [], after, foreignOrderIds = [], targetIds = [], onRowClick, compact, emptyState, className }: OrderDiffTableProps) {
  if (rows.length === 0) return <>{emptyState ?? <p className="p-3 text-sm text-ink-3">No orders to compare. Choose a recovery scenario to inspect its repair scope.</p>}</>
  return (
    <div className={cn('min-w-0 max-w-full overflow-x-auto', className)} tabIndex={0} role="region" aria-label="Order comparisons">
      <table className="w-full min-w-[640px] border-separate border-spacing-0 text-left text-[13px]">
        <thead>
          <tr className="text-xs text-ink-3">
            <th scope="col" className="px-3 pb-2 font-medium">Order</th>
            {FIELDS.map((f) => (
              <th key={f} scope="col" className="px-3 pb-2 font-medium">{fieldLabel(f)}</th>
            ))}
            <th scope="col" className="px-3 pb-2 text-right font-medium">State</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const repaired = repairedIds.includes(row.order_id)
            const foreign = foreignOrderIds.includes(row.order_id)
            const targeted = targetIds.includes(row.order_id)
            const cond = CONDITION[row.condition]
            const afterValues = after?.[row.order_id]
            const deleted = row.condition === 'deleted_tombstoned' || row.current === null
            return (
              <tr
                key={row.order_id}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                onKeyDown={onRowClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRowClick(row) } } : undefined}
                className={cn('group transition-colors', targeted && 'bg-[color-mix(in_srgb,var(--layer-armoriq)_8%,transparent)]', onRowClick && 'cursor-pointer hover:bg-surface-2 active:bg-surface-3')}
              >
                <td className={cn('border-t border-line px-3 align-top', compact ? 'py-2' : 'py-3')}>
                  <div className="font-mono text-[13px] font-medium text-ink">{row.order_id}</div>
                  <div className="max-w-[170px] truncate text-xs text-ink-3" title={row.customer_name}>{row.customer_name}</div>
                </td>
                {FIELDS.map((f) => (
                  <td key={f} className={cn('border-t border-line px-3 align-top', compact ? 'py-2' : 'py-3')}>
                    <FieldCell
                      field={f}
                      row={row}
                      repaired={repaired}
                      deleted={deleted}
                      foreign={foreign}
                      afterValues={afterValues}
                    />
                  </td>
                ))}
                <td className={cn('border-t border-line px-3 text-right align-top', compact ? 'py-2' : 'py-3')}>
                  {foreign ? (
                    <Badge tone="neutral" dashed>Other tenant</Badge>
                  ) : repaired ? (
                    <Badge tone="good" icon={<cond.icon />}>Repaired</Badge>
                  ) : (
                    <Badge tone={cond.tone} icon={<cond.icon />}>{cond.label}</Badge>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function FieldCell({
  field,
  row,
  repaired,
  deleted,
  foreign,
  afterValues,
}: {
  field: Field
  row: SnapshotDiffRow
  repaired: boolean
  deleted: boolean
  foreign: boolean
  afterValues: SnapshotOrderValues | null | undefined
}) {
  const snap = row.snapshot
  const cur = row.current
  const differs = row.differing_fields.includes(field)

  if (foreign) {
    return <span className="text-ink-3">{render(field, cur ?? snap)}</span>
  }
  if (deleted) {
    // The record was deleted after the snapshot. Show what the snapshot held, dimmed, so nobody restores it.
    return field === 'total_cents' ? (
      <div>
        <span className="text-ink-3">Deleted</span>
        <div className="text-xs text-ink-3 line-through decoration-1">{render(field, snap)}</div>
      </div>
    ) : (
      <span className="text-ink-3">{render(field, snap)}</span>
    )
  }
  if (!differs) {
    const v = repaired ? (afterValues ?? snap) : cur
    return <span className="text-ink-2">{render(field, v)}</span>
  }
  if (repaired) {
    const restored = afterValues ?? snap
    return (
      <div>
        <span key="repaired" className="morph-good -mx-1.5 inline-block rounded-md px-1.5 py-0.5 font-medium tabular">
          {render(field, restored)}
        </span>
        <div className="mt-0.5 text-xs text-ink-3">was {render(field, cur)}</div>
      </div>
    )
  }
  if (row.condition === 'changed_after_snapshot') {
    // A legitimate later update. The snapshot value must NOT be restored.
    return (
      <div>
        <span className="font-medium tabular" style={{ color: 'var(--diff-keep)' }}>{render(field, cur)}</span>
        <div className="mt-0.5 text-xs text-ink-3">Snapshot said {render(field, snap)}</div>
      </div>
    )
  }
  return (
    <div>
      <span key="damaged" className="-mx-1.5 inline-block rounded-md px-1.5 py-0.5 font-medium tabular" style={{ color: 'var(--diff-bad)', background: 'color-mix(in srgb, var(--diff-bad) 12%, transparent)' }}>
        {render(field, cur)}
      </span>
      <div className="mt-0.5 inline-flex items-center gap-1 text-xs text-ink-3">
        <ArrowRight className="size-3" aria-hidden />
        snapshot {render(field, snap)}
      </div>
    </div>
  )
}
