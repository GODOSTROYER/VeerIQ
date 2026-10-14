import { useMemo } from 'react'
import { motion } from 'motion/react'
import { ArrowRight, Check, Circle, Layers, Lock, ShieldAlert } from 'lucide-react'
import type { AppState, ExecutionReceipt, InvariantCheck, SnapshotDiffRow, SnapshotOrderValues } from '@/api/types'
import { EMPTY_TEXT, formatDateTime } from '@/lib/format'
import { CONDITION, fieldLabel, INVARIANT_STATUS } from '@/lib/labels'
import { Technical } from '@/lib/detail'
import { T, useMotionOK } from '@/lib/motion'
import { NumberRoll } from '@/components/motion'
import { Badge, Button, Digest, Disclosure, EmptyState, ErrorState, Panel, Skeleton } from '@/components/ui'
import { DefenseStack } from '@/components/domain'
import { formatFieldValue, isEmptyValue, type ProposalItem } from './model'
import { isHeld } from './proof'

type Field = keyof SnapshotOrderValues
const FIELD_ORDER: Field[] = ['total_cents', 'shipping_region', 'status']

/** Receipts preserve the damaged values even when today's data is already restored. */
export function withPreRepairValues(rows: SnapshotDiffRow[], receipts: ExecutionReceipt[]): SnapshotDiffRow[] {
  const before = new Map<string, Map<string, unknown>>()
  for (const r of receipts) {
    if (r.result !== 'committed') continue
    for (const c of r.changes) {
      if (!before.has(c.row_id)) before.set(c.row_id, new Map())
      if (!before.get(c.row_id)!.has(c.field)) before.get(c.row_id)!.set(c.field, c.before)
    }
  }
  return rows.map(row => {
    const fields = before.get(row.order_id)
    if (!fields || row.current === null) return row
    const current = { ...row.current } as Record<string, unknown>
    for (const [field, value] of fields) current[field] = value
    return { ...row, condition: 'damaged', current: current as unknown as SnapshotOrderValues, differing_fields: Array.from(new Set([...row.differing_fields, ...fields.keys()])) }
  })
}

export function afterValuesFromReceipts(rows: SnapshotDiffRow[], receipts: ExecutionReceipt[]): Record<string, SnapshotOrderValues> {
  const out: Record<string, SnapshotOrderValues> = {}
  for (const r of receipts) {
    if (r.result !== 'committed') continue
    for (const c of r.changes) {
      const row = rows.find(x => x.order_id === c.row_id)
      const base = out[c.row_id] ?? (row ? { ...(row.current ?? row.snapshot) } : undefined)
      if (!base) continue
      ;(base as unknown as Record<string, unknown>)[c.field] = c.after
      out[c.row_id] = base
    }
  }
  return out
}

function FieldLine({ field, row, repaired, after }: { field: Field; row: SnapshotDiffRow; repaired: boolean; after: SnapshotOrderValues | undefined }) {
  const motionOK = useMotionOK()
  const current = row.current?.[field]
  const snapshot = row.snapshot[field]
  const restored = after?.[field] ?? snapshot
  const value = repaired ? restored : current
  if (row.condition === 'changed_after_snapshot') return <li className="text-xs leading-relaxed"><span className="text-ink-3">{fieldLabel(field)} </span><span className="text-info">{formatFieldValue(field, current)} kept.</span><Technical><span className="text-ink-3">Snapshot: {formatFieldValue(field, snapshot)}</span></Technical></li>
  return <li className="grid grid-cols-[minmax(80px,1fr)_minmax(0,1.8fr)] items-baseline gap-x-2 gap-y-0.5 text-xs">
    <span className="text-ink-3">{fieldLabel(field)}</span>
    <div className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
      {repaired && <span className="tabular text-ink-3 line-through">{formatFieldValue(field, current)}</span>}
      {repaired && <ArrowRight className="size-3 self-center text-ink-3" aria-hidden />}
      <span className="tabular font-medium" style={{ color: isEmptyValue(value) ? 'var(--text-3)' : repaired ? 'var(--outcome-allow)' : 'var(--outcome-block)' }}>
        {typeof value === 'number' ? <NumberRoll value={value} format={n => formatFieldValue(field, n)} /> : <motion.span key={String(value)} initial={motionOK && repaired ? { opacity: 0, y: 4 } : false} animate={{ opacity: 1, y: 0 }} transition={T.base}>{formatFieldValue(field, value)}</motion.span>}
      </span>
      {!repaired && <><ArrowRight className="size-3 self-center text-ink-3" aria-hidden /><span className="tabular text-ink-2">{formatFieldValue(field, snapshot)}</span></>}
    </div>
  </li>
}

function OrderRow({ row, repaired, targeted, after }: { row: SnapshotDiffRow; repaired: boolean; targeted: boolean; after: SnapshotOrderValues | undefined }) {
  const deleted = row.condition === 'deleted_tombstoned' || row.current === null
  const fields = !deleted ? FIELD_ORDER.filter(f => row.differing_fields.includes(f)) : []
  return <li className="py-3 first:pt-0 last:pb-0">
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0"><span className="font-mono text-[13px] font-medium text-ink">{row.order_id}</span><p className="mt-0.5 text-xs text-ink-3">{row.customer_name}</p></div>
      <span className="flex shrink-0 items-center gap-1 text-xs" style={{ color: repaired ? 'var(--outcome-allow)' : undefined }}>{repaired && <Check className="size-3.5" aria-hidden />}{repaired ? 'Restored' : CONDITION[row.condition].label}</span>
    </div>
    {deleted ? <p className="mt-2 text-xs text-ink-2">Deleted after the snapshot. It stays deleted.</p> : fields.length ? <ul className="mt-2 space-y-1.5">{fields.map(field => <FieldLine key={field} field={field} row={row} repaired={repaired} after={after} />)}</ul> : <p className="mt-2 text-xs text-ink-2">{formatFieldValue('total_cents', row.current?.total_cents)}, unchanged.</p>}
    {row.condition === 'on_hold' && !repaired && <p className="mt-2 text-xs text-ink-2">A hold protects this order. The repair is not applied.</p>}
    <Technical>{targeted && <p className="mt-1 text-xs text-ink-3">Targeted by the selected request.</p>}</Technical>
  </li>
}

export interface OrdersProps {
  rows: SnapshotDiffRow[]
  repairedIds: string[]
  targetIds: string[]
  after: Record<string, SnapshotOrderValues>
  generationMismatch?: boolean
}

function OrdersList({ rows, repairedIds, targetIds, after, generationMismatch = false }: OrdersProps) {
  const work = rows.filter(r => repairedIds.includes(r.order_id) || targetIds.includes(r.order_id) || (!generationMismatch && (r.condition === 'damaged' || r.condition === 'on_hold')) || (generationMismatch && after[r.order_id]))
  const keep = rows.filter(r => !work.includes(r))
  const render = (row: SnapshotDiffRow) => <OrderRow key={row.order_id} row={row} repaired={repairedIds.includes(row.order_id)} targeted={targetIds.includes(row.order_id)} after={after[row.order_id]} />
  return <div>{work.length ? <ul className="divide-y divide-line">{work.map(render)}</ul> : <p className="text-xs text-ink-2">No targeted orders to show yet.</p>}{keep.length > 0 && <Disclosure summary={`${generationMismatch ? 'Other orders in current data' : 'Other orders kept as they are'} (${keep.length})`} className="mt-4"><ul className="divide-y divide-line">{keep.map(render)}</ul></Disclosure>}</div>
}

function Checks({ checks, pending }: { checks: InvariantCheck[]; pending: boolean }) {
  const motionOK = useMotionOK()
  if (!checks.length) return <EmptyState compact title="No protected checks recorded" description="This run has no individual protected-check results to show." />
  return <ul className="divide-y divide-line">{checks.map(check => {
    const held = !pending && isHeld(check)
    const violated = !pending && check.status === 'violated'
    return <li key={check.check_id} className="py-2.5 first:pt-0 last:pb-0" role={violated ? 'alert' : undefined}>
      <div className="flex items-start gap-2"><motion.span key={held ? 'held' : violated ? 'violated' : 'pending'} initial={false} animate={{ color: held ? 'var(--outcome-allow)' : violated ? 'var(--outcome-block)' : 'var(--text-3)' }} transition={motionOK ? T.fast : { duration: 0 }} className="mt-0.5 shrink-0">{held ? <Check className="size-4" aria-hidden /> : violated ? <ShieldAlert className="size-4" aria-hidden /> : <Circle className="size-4" aria-hidden />}</motion.span><div className="min-w-0 flex-1"><p className="text-[13px] leading-snug text-ink-2">{check.label}</p><p className="mt-0.5 text-xs text-ink-3">{pending ? 'Awaiting recorded verification' : INVARIANT_STATUS[check.status].label}</p><Technical><div className="mt-2 text-xs text-ink-3"><p>{check.detail}</p><Disclosure summary="Check evidence"><pre className="overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sunken p-2 font-mono text-[11px]">{JSON.stringify(check, null, 2)}</pre></Disclosure></div></Technical></div></div>
    </li>
  })}</ul>
}

function BeaconDetails({ beacon, attempts, checkStatus, live }: { beacon: AppState['beacon'] | undefined; attempts: number; checkStatus: InvariantCheck['status'] | undefined; live: boolean }) {
  if (!live) {
    if (!checkStatus) return <p className="text-xs text-ink-3">Tenant isolation was not recorded for this run.</p>
    return <div className="space-y-2 text-xs text-ink-2"><p>Recorded tenant-isolation check · {INVARIANT_STATUS[checkStatus].label}</p><p>Shown from this run’s protected-check evidence.</p></div>
  }
  if (!beacon) return <Skeleton className="h-12 rounded-lg" />
  const intact = beacon.untouched && beacon.checksum === beacon.expected_checksum && checkStatus !== 'violated'
  return <div className="space-y-2 text-xs text-ink-2"><p className="flex items-center gap-2">{intact ? <Lock className="size-3.5 text-allow" /> : <ShieldAlert className="size-3.5 text-block" />}Beacon Coffee Co. · {intact ? 'Current data matches its seal' : 'Current data changed'}</p><p>Another tenant: no grant, signed action or permission for it.</p><Digest value={beacon.checksum} label="Beacon checksum" head={10} tail={6} /><p>Matches sealed checksum: {beacon.checksum === beacon.expected_checksum ? 'Yes' : 'No'} · {beacon.order_count} orders</p>{attempts > 0 && <p>{attempts} cross-tenant requests blocked before any repair was prepared or written.</p>}</div>
}

export interface EffectsColumnProps {
  selected: ProposalItem | undefined
  pinned: boolean
  onFollowLatest: () => void
  actionText: string | undefined
  diffRows: SnapshotDiffRow[] | undefined
  diffError: Error | undefined
  onRetryDiff: () => void
  allReceipts: ExecutionReceipt[]
  repairedIds: string[]
  targetIds: string[]
  targetRecordIds: string[]
  checks: InvariantCheck[] | undefined
  recordedChecks: InvariantCheck[] | undefined
  checksAreRecorded: boolean
  checksError: Error | undefined
  appState: AppState | undefined
  beaconAttempts: number
  generationMismatch: boolean
  /** Only recorded checks that have reached the visible replay prefix may tick. */
  replaying?: boolean
  live?: boolean
  workflow?: string
  /** Visible receipts for replay/live verification; allReceipts still reconstructs damaged values. */
  visibleReceipts?: ExecutionReceipt[]
}

export function EffectsColumn(p: EffectsColumnProps) {
  const rows = useMemo(() => p.diffRows ? withPreRepairValues(p.diffRows, p.allReceipts) : undefined, [p.diffRows, p.allReceipts])
  const after = useMemo(() => rows ? afterValuesFromReceipts(rows, p.allReceipts) : {}, [rows, p.allReceipts])
  const visibleReceipts = p.visibleReceipts ?? p.allReceipts.filter(r => r.changes.some(c => p.repairedIds.includes(c.row_id)))
  const imported = p.workflow === 'rewindsafe.import_recovery'
  const recorded = p.checksAreRecorded ? p.recordedChecks ?? [] : undefined
  const checks = recorded ?? (p.live ? p.checks : undefined)
  const guarded = checks?.filter(c => c.category !== 'repair' && c.category !== 'tenant_isolation')
  const pending = !recorded && (!!p.replaying || !p.live || p.generationMismatch)
  const held = pending ? 0 : guarded?.filter(isHeld).length ?? 0
  const violated = pending ? 0 : guarded?.filter(c => c.status === 'violated').length ?? 0
  const importedChanges = visibleReceipts.filter(r => r.result === 'committed').flatMap(receipt => receipt.changes.map(change => ({ receipt, change })))
  return <div className="space-y-4">
    <Panel title={imported ? 'Imported records' : 'Orders'} subtitle={imported ? 'Values recorded in this run’s committed receipts' : 'Damaged values → approved values'}>
      {imported ? <div className="space-y-4">
        {importedChanges.length ? <ul className="divide-y divide-line">{Array.from(new Set(importedChanges.map(({ change }) => change.row_id))).map(recordId => {
          const changes = importedChanges.filter(({ change }) => change.row_id === recordId)
          return <li key={recordId} className="py-3 first:pt-0 last:pb-0">
            <div className="flex items-start justify-between gap-2"><span className="font-mono text-[13px] font-medium text-ink">{recordId}</span><Badge size="sm" tone="good">Restored</Badge></div>
            <ul className="mt-2 space-y-1.5">{changes.map(({ receipt, change }) => <li key={`${receipt.operation_id}:${change.field}`} className="grid grid-cols-[minmax(80px,1fr)_minmax(0,1.8fr)] gap-x-2 text-xs"><span className="text-ink-3">{change.field.replaceAll('_', ' ')}</span><span className="break-words text-ink-2"><span className="text-ink-3">{isEmptyValue(change.before) ? EMPTY_TEXT : String(change.before)}</span><ArrowRight className="mx-1 inline size-3 text-ink-3" aria-hidden /><span className={isEmptyValue(change.after) ? 'font-medium text-ink-3' : 'font-medium text-allow'}>{isEmptyValue(change.after) ? EMPTY_TEXT : String(change.after)}</span></span></li>)}</ul>
            <p className="mt-2 text-[11px] text-ink-3">Receipt {changes[0]?.receipt.operation_id}</p>
          </li>
        })}</ul> : <div>
          {p.targetRecordIds.length ? <><p className="text-xs text-ink-2">No committed record changes are recorded yet.</p><p className="mt-2 text-[11px] text-ink-3">Authorized record IDs: {p.targetRecordIds.join(', ')}</p></> : <EmptyState compact title="No imported record changes" description="A committed receipt will identify each repaired record and field." />}
        </div>}
      </div> : <>
      {p.generationMismatch && <p className="mb-3 text-xs leading-relaxed text-ink-3">The demo was reset after this run. Receipts retain its repair values; other values reflect current data.</p>}
      {p.diffError && !rows ? <ErrorState compact error={p.diffError} title="Orders did not load" onRetry={p.onRetryDiff} /> : !rows ? <div role="status" aria-label="Loading orders" className="space-y-3">{[0, 1].map(i => <Skeleton key={i} className="h-24 rounded-lg" />)}</div> : !rows.length ? <EmptyState compact title="No orders in this incident" description="The snapshot has no orders to compare." /> : <OrdersList rows={rows} repairedIds={p.repairedIds} targetIds={p.targetIds} after={after} generationMismatch={p.generationMismatch} />}
      </>}
    </Panel>
    <Panel title="Must stay true" actions={guarded ? <Badge size="sm" tone={violated ? 'bad' : held ? 'good' : 'neutral'}>{guarded.length ? violated ? `${violated} violated` : `${held}/${guarded.length} checked` : 'Not recorded'}</Badge> : undefined}>
      {p.checksError && !checks ? <ErrorState compact error={p.checksError} title="Protected checks did not load" /> : !guarded ? <EmptyState compact title="Detailed historical checks not recorded" description="Current data cannot certify what the run preserved. See the run’s recorded summary and receipts." /> : <Checks checks={guarded} pending={pending} />}
      <Technical><div className="mt-4 border-t border-line pt-3"><BeaconDetails beacon={p.appState?.beacon} attempts={p.beaconAttempts} checkStatus={checks?.find(c => c.category === 'tenant_isolation')?.status} live={!!p.live} /></div></Technical>
    </Panel>
    <Technical><Panel title="Selected request’s full defence stack" subtitle={p.actionText} icon={<Layers className="size-4" />} actions={p.pinned ? <Button size="sm" variant="ghost" onClick={p.onFollowLatest}>Follow latest</Button> : undefined}>{p.selected ? <DefenseStack decisions={p.selected.decisions} animateKey={p.selected.proposalId} compact /> : <EmptyState compact title="Waiting for a request" description="Select a feed step to inspect every layer’s decision." />}<p className="mt-3 text-xs text-ink-3">ArmorIQ binds tool names, VeerIQ binds arguments.</p></Panel>{p.appState && <p className="mt-3 break-all text-xs text-ink-3">Snapshot <span className="font-mono">{p.appState.snapshot.snapshot_id}</span> · Taken {formatDateTime(p.appState.snapshot.taken_at)}</p>}</Technical>
  </div>
}
