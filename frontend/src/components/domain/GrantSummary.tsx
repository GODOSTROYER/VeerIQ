import type { ReactNode } from 'react'
import { Ban, Clock, FileCheck2, Gauge, Package, ShieldCheck, UserCheck, type LucideIcon } from 'lucide-react'
import type { TaskGrant } from '@/api/types'
import { Technical, useDetail } from '@/lib/detail'
import { cn } from '@/lib/cn'
import { tint } from '@/lib/color'
import { formatDateTime, formatDollars, pluralize } from '@/lib/format'
import { fieldLabel, GRANT_STATUS, resourceLabel, TOOL_LABELS, tenantName, toolLabel, toolSummary } from '@/lib/labels'
import { Badge, Digest, Disclosure, KeyValue, KeyValueGrid } from '@/components/ui'

export interface GrantSummaryProps {
  grant: TaskGrant
  /** compact: one glanceable card. full: the exact authority, section by section. */
  variant?: 'compact' | 'full'
  /** Show the grant as the plan ArmorIQ will sign is simulated (changes one sentence of copy). */
  simulated?: boolean
  className?: string
}

function ids(map: Record<string, string[]>, kind: string): string[] {
  return map[kind] ?? []
}

/** Minutes a draft grant lasts once authorized (derived from the API's own timestamps). */
function validityMinutes(grant: TaskGrant): number | null {
  const mins = Math.round((new Date(grant.expires_at).getTime() - new Date(grant.created_at).getTime()) / 60000)
  return mins > 0 && mins <= 24 * 60 ? mins : null
}

export function expiryCopy(grant: TaskGrant): string {
  if (grant.status === 'draft') {
    const m = validityMinutes(grant)
    return m ? `Lasts ${m} minutes once you authorize it` : `Expires ${formatDateTime(grant.expires_at)}`
  }
  return `Expires ${formatDateTime(grant.expires_at)}`
}

export function GrantSummary({ grant, variant = 'full', simulated, className }: GrantSummaryProps) {
  const { technical } = useDetail()
  const recordNoun = grant.workflow === 'rewindsafe.import_recovery' ? 'record' : 'order'
  const orders = ids(grant.resources, 'order')
  const reviewOrders = ids(grant.reviewable, 'order')
  const tenant = tenantName(grant.tenant_id)
  const snapshotId = String(grant.source_constraints.snapshot_id ?? ids(grant.resources, 'snapshot')[0] ?? '')
  const snapshotDigest = grant.source_constraints.snapshot_digest ? String(grant.source_constraints.snapshot_digest) : null
  const allOrders = [...new Set([...orders, ...reviewOrders])]

  if (variant === 'compact') {
    return (
      <div className={cn('space-y-3', className)}>
        <p className="text-sm leading-snug text-ink">{grant.purpose}</p>
        <div className="flex flex-wrap gap-1.5">
          <Badge tone="info" icon={<Package />}>{tenant}</Badge>
          <Badge tone="neutral">{pluralize(allOrders.length, recordNoun)}</Badge>
          <Badge tone="neutral">{grant.fields.map(fieldLabel).join(', ') || 'No fields'}</Badge>
          {reviewOrders.length > 0 && <Badge tone="hold" icon={<UserCheck />}>Needs a second reviewer</Badge>}
          <Badge tone={grant.status === 'active' ? 'good' : 'neutral'}>{GRANT_STATUS[grant.status]}</Badge>
        </div>
        <p className="text-xs text-ink-3">{expiryCopy(grant)}.</p><Technical><p className="text-xs text-ink-3">{pluralize(grant.allowed_tools.length, 'tool')} allowed, {pluralize(grant.prohibited_effects.length, 'hard prohibition')}.</p></Technical>
      </div>
    )
  }

  const exactScope = (
    <div className="space-y-5">
      <p className="text-[15px] leading-relaxed text-ink">{grant.purpose}</p>

      <Block icon={Package} title="Scope" hint="The only data the agent may touch.">
        <KeyValueGrid columns={2}>
          <KeyValue label="Tenant">{tenant}</KeyValue>
          {grant.incident_id && <KeyValue label="Incident" mono>{grant.incident_id}</KeyValue>}
          <KeyValue label={`May repair ${resourceLabel(recordNoun, orders.length)}`} mono>
            {orders.length ? orders.join(', ') : 'None directly'}
          </KeyValue>
          <KeyValue label="May change these fields">{grant.fields.map(fieldLabel).join(', ') || 'None'}</KeyValue>
        </KeyValueGrid>
      </Block>

      <Block
        icon={ShieldCheck}
        title="Allowed tools"
        hint={
          simulated
            ? 'In this session a local simulation stands in for ArmorIQ and enforces exactly this list.'
            : 'This is the plan ArmorIQ signs. Any other tool is stopped before it runs.'
        }
        tint="var(--layer-armoriq)"
      >
        <ul className="grid gap-1.5 sm:grid-cols-2">
          {grant.allowed_tools.map((t) => (
            <li key={t} className="flex items-start gap-2.5 rounded-lg border border-line bg-surface px-3 py-2">
              <span className="mt-1.5 size-1.5 shrink-0 rounded-full" style={{ background: 'var(--layer-armoriq)' }} aria-hidden />
              <div className="min-w-0">
                <p className="text-[13px] font-medium text-ink">{toolLabel(t)}</p>
                {toolSummary(t) && <p className="text-xs leading-snug text-ink-3">{toolSummary(t)}</p>}
              </div>
              {TOOL_LABELS[t]?.kind === 'mutate' && (
                <Badge tone="hold" size="sm" className="ml-auto">Writes data</Badge>
              )}
            </li>
          ))}
        </ul>
      </Block>

      <Block icon={UserCheck} title="Needs a second reviewer" hint="A different person must approve the exact change first." tint="var(--layer-approval)">
        {reviewOrders.length > 0 || grant.limits.review_threshold_cents > 0 ? (
          <ul className="space-y-1.5 text-[13px] text-ink-2">
            {reviewOrders.length > 0 && (
              <li>
                {resourceLabel(recordNoun, reviewOrders.length).replace(/^./, (c) => c.toUpperCase())}{' '}
                <span className="font-mono text-ink">{reviewOrders.join(', ')}</span> always need review.
              </li>
            )}
            <li>Any repair restoring more than <span className="tabular font-medium text-ink">{formatDollars(grant.limits.review_threshold_cents)}</span> needs review.</li>
          </ul>
        ) : (
          <p className="text-[13px] text-ink-3">Nothing in this grant needs review.</p>
        )}
      </Block>

      <Block icon={Ban} title="Hard prohibitions" hint="Never allowed under this grant, whatever the agent is told." tint="var(--outcome-block)">
        <ul className="grid gap-1.5 sm:grid-cols-2">
          {grant.prohibited_effects.map((p) => (
            <li key={p} className="flex items-start gap-2 text-[13px] leading-snug text-ink-2">
              <Ban className="mt-0.5 size-3.5 shrink-0" style={{ color: 'var(--outcome-block)' }} aria-hidden />
              {p}
            </li>
          ))}
        </ul>
      </Block>

      <Block icon={Gauge} title="Limits & expiry">
        <KeyValueGrid columns={4}>
          <KeyValue label="Repairs allowed">{grant.limits.max_commits}</KeyValue>
          <KeyValue label="Rows per repair">{grant.limits.max_rows_per_commit}</KeyValue>
          <KeyValue label="Agent steps">{grant.limits.max_steps}</KeyValue>
          <KeyValue label="Re-plans after a stop">{grant.limits.max_replans}</KeyValue>
        </KeyValueGrid>
        <p className="mt-3 inline-flex items-center gap-1.5 text-[13px] text-ink-2">
          <Clock className="size-3.5 text-ink-3" aria-hidden />
          {expiryCopy(grant)}
        </p>
      </Block>

      <Block icon={FileCheck2} title="Source snapshot" hint="Repairs may only use values from this approved snapshot.">
        <KeyValueGrid columns={2}>
          <KeyValue label="Snapshot" mono>{snapshotId || 'None'}</KeyValue>
          <KeyValue label="Snapshot digest">
            <Digest value={snapshotDigest} label="snapshot digest" />
          </KeyValue>
          <KeyValue label="Grant digest" hint="Changes if any term of this grant changes.">
            <Digest value={grant.grant_digest} label="grant digest" />
          </KeyValue>
        </KeyValueGrid>
      </Block>
    </div>
  )
  return <div className={cn('space-y-4', className)}>
    <p className="text-lg font-medium leading-relaxed text-ink">The agent may repair {pluralize(allOrders.length, recordNoun)}, change {pluralize(grant.fields.length, 'field')}, and commit {grant.limits.max_commits === 1 ? 'once' : `${grant.limits.max_commits} times`}; {simulated ? 'a local simulation will enforce' : 'ArmorIQ will sign'} a plan of {pluralize(grant.allowed_tools.length, 'action')}.</p>
    <p className="text-sm text-ink-2">Only approved snapshot values may be restored, within {tenant}. ArmorIQ binds tool names; VeerIQ binds arguments.</p>
    <div className="border-y border-line py-3 text-[13px] leading-relaxed text-ink-2">
      <p><span className="font-medium text-ink">A second person must approve </span>{reviewOrders.length ? `the ${pluralize(reviewOrders.length, `reviewable ${recordNoun}`)} and ` : ''}any repair restoring more than {formatDollars(grant.limits.review_threshold_cents)}.</p>
      <p className="mt-2">{expiryCopy(grant)}. Deleted records, revoked access, later updates and other tenants remain protected.</p>
    </div>
    {technical ? exactScope : <Disclosure summary="Read the exact scope and restrictions">{exactScope}</Disclosure>}
  </div>

}

function Block({
  icon: Icon,
  title,
  hint,
  tint: color = 'var(--text-2)',
  children,
}: {
  icon: LucideIcon
  title: string
  hint?: string
  tint?: string
  children: ReactNode
}) {
  return (
    <section>
      <div className="mb-2.5 flex flex-wrap items-center gap-2">
        <span className="grid size-6 place-items-center rounded-md" style={{ color, background: tint(color, 14) }}>
          <Icon className="size-3.5" aria-hidden />
        </span>
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {hint && <span className="text-xs text-ink-3">{hint}</span>}
      </div>
      <div className="pl-8">{children}</div>
    </section>
  )
}
