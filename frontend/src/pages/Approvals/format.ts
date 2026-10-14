import type { ApprovalWithPreview, ExecutionManifest, Identity, SnapshotDiffRow } from '@/api/types'
import { fieldLabel } from '@/lib/labels'
import { formatMoney, titleCase } from '@/lib/format'

/** Show one manifest value the way a finance reviewer expects to read it. */
export function formatChangeValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (field.endsWith('_cents') && typeof value === 'number') return formatMoney(value)
  return String(value)
}

export interface ConstraintLine {
  label: string
  value: string
}

/** Turn the machine state constraints into sentences a reviewer can check. */
export function describeConstraints(constraints: Record<string, unknown>): ConstraintLine[] {
  const lines: ConstraintLine[] = []
  for (const [key, value] of Object.entries(constraints)) {
    if (key === 'authority_epoch') {
      lines.push({ label: 'Authority unchanged', value: `No access, hold or deletion change since version ${String(value)}` })
    } else if (key === 'row_versions' && value && typeof value === 'object') {
      for (const [row, version] of Object.entries(value as Record<string, unknown>)) {
        lines.push({ label: `Order ${row} unedited`, value: `Still at row version ${String(version)}` })
      }
    } else if (key === 'fixture_generation') {
      lines.push({ label: 'Same demo data', value: `Generation ${String(value)}` })
    } else if (Array.isArray(value)) {
      lines.push({ label: titleCase(key), value: value.length ? value.join(', ') : '—' })
    } else if (value !== null && typeof value === 'object') {
      lines.push({ label: titleCase(key), value: JSON.stringify(value) })
    } else {
      lines.push({ label: titleCase(key), value: String(value) })
    }
  }
  return lines
}

export function manifestOf(approval: ApprovalWithPreview): ExecutionManifest | null {
  return approval.manifest ?? null
}

export function fieldText(field: string): string {
  return fieldLabel(field)
}

export function personName(id: string | null, identities: Identity[]): string {
  if (!id) return 'No reviewer'
  return identities.find((i) => i.identity_id === id)?.name ?? id
}

/** Describe the immutable repair; the diff is used only to look up customer names. */
export function repairSummary(approval: ApprovalWithPreview, orders?: SnapshotDiffRow[], withAmount = true): string {
  const manifest = manifestOf(approval)
  const targets = approval.targets.length ? approval.targets : [...new Set(manifest?.changes.map((c) => c.row_id) ?? [])]
  if (!targets.length) return 'Review the requested repair'
  const names = targets.map((id) => {
    const customer = orders?.find((o) => o.order_id === id)?.customer_name
    return `${id}${customer ? ` for ${customer}` : ''}`
  })
  const amount = manifest && withAmount ? ` to ${formatMoney(manifest.restored_value_cents)}` : ''
  return `Restore ${targets.length === 1 ? 'order' : 'orders'} ${names.join(', ')}${amount}`
}
