import { useEffect, useId, useMemo, useState, type ReactNode } from 'react'
import { ArrowRight, Check, Download, FileJson2, TriangleAlert, Info } from 'lucide-react'
import type { Decision, ExecutionManifest, ExecutionReceipt, RunEvent } from '@/api/types'
import { formatClock, formatDateTime, hasTime } from '@/lib/format'
import { fieldLabel, invariantLabel, toolLabel, TONE_COLOR, INVARIANT_STATUS, type Tone } from '@/lib/labels'
import { isSimulatedEnforcement, sourceLabel, type EnforcementFacts } from '@/lib/layers'
import { Technical } from '@/lib/detail'
import { DUR } from '@/lib/motion'
import { Badge, Button, Digest, Disclosure, Drawer, EmptyState, ErrorState, LayerChip, OutcomeChip, SkeletonLines, Tabs, type TabItem } from '@/components/ui'
import { formatFieldValue, isEmptyValue } from './model'
import type { ProofLine } from './proof'

type TabId = 'decisions' | 'manifests' | 'receipts' | 'raw'
export interface EvidenceDrawerProps {
  open: boolean
  onClose: () => void
  runId: string
  proof: ProofLine[]
  decisions: Array<{ decision: Decision; tool: string | undefined }>
  manifests: ExecutionManifest[]
  receipts: ExecutionReceipt[]
  events: RunEvent[]
  /** Shared facts behind every "Live" or "Simulated" label on the page. */
  enforcement: EnforcementFacts
  onExport: () => void
  exporting: boolean
  loading?: boolean
  error?: Error
}
const PROOF_ICON: Record<Tone, typeof Check> = { good: Check, bad: TriangleAlert, hold: TriangleAlert, warn: TriangleAlert, info: Info, neutral: Info }

function JsonRecord({ value, summary = 'Exact record' }: { value: unknown; summary?: ReactNode }) {
  return <Disclosure summary={summary}><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sunken p-3 font-mono text-[11px] leading-relaxed text-ink-2">{JSON.stringify(value, null, 2)}</pre></Disclosure>
}

function Decisions({ rows }: { rows: EvidenceDrawerProps['decisions'] }) {
  if (!rows.length) return <EmptyState compact title="No gate decisions recorded yet" description="As the agent proposes requests, each gate’s verdict appears here. The export also includes the grant and signed plan." />
  return <ul className="divide-y divide-line">{rows.map(({ decision: d, tool }) => <li key={d.decision_id} className="py-4 first:pt-0">
    <div className="flex flex-wrap items-center gap-2"><p className="min-w-0 flex-1 text-sm font-medium text-ink">{tool ? toolLabel(tool) : 'Sign the plan'}</p><LayerChip layer={d.layer} compact /><OutcomeChip outcome={d.outcome} shadow={d.shadow} simulated={d.simulated} size="sm" /></div>
    <p className="mt-2 text-[13px] leading-relaxed text-ink-2">{d.shadow ? 'A second check: it did not make the final decision. ' : d.decisive ? 'This layer made the final decision. ' : ''}{d.invariant ? invariantLabel(d.invariant) : d.outcome === 'allow' ? 'This request passed the layer’s checks.' : d.outcome === 'hold' ? 'A second person must review the exact change.' : d.outcome === 'unavailable' ? 'The check was unavailable. The request failed closed.' : d.reason}</p>
    <Technical><div className="mt-2 space-y-2 text-xs text-ink-3"><p>{sourceLabel(d)} · {d.latency_ms != null ? `${Math.round(d.latency_ms)} ms` : 'No latency recorded'} · Decisive: {d.decisive ? 'Yes' : 'No'} · Shadow: {d.shadow ? 'Yes' : 'No'} · Simulated: {d.simulated ? 'Yes' : 'No'}</p><p>{d.reason}</p><JsonRecord value={d} summary="Decision, source and raw reason" /></div></Technical>
  </li>)}</ul>
}

function Change({ rowId, field, before, after }: { rowId: string; field: string; before: unknown; after: unknown }) {
  return <li className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] gap-x-3 gap-y-1 py-2 text-[13px]">
    <div><span className="font-mono text-xs text-ink">{rowId}</span><span className="mt-0.5 block text-xs text-ink-3">{fieldLabel(field)}</span></div>
    <div className="tabular flex flex-wrap items-baseline gap-x-2 gap-y-1"><span className="text-ink-3 line-through">{formatFieldValue(field, before)}</span><ArrowRight className="size-3 self-center text-ink-3" aria-hidden /><span className={isEmptyValue(after) ? 'font-medium text-ink-3' : 'font-medium text-allow'}>{formatFieldValue(field, after)}</span></div>
  </li>
}

function Manifests({ manifests }: { manifests: ExecutionManifest[] }) {
  if (!manifests.length) return <EmptyState compact title="No repair has been prepared" description="Once the agent prepares a repair, its exact proposed values appear here. Preparation does not change any data." />
  return <ul className="divide-y divide-line">{manifests.map((m, index) => <li key={m.manifest_id} className="py-4 first:pt-0">
    <div className="flex flex-wrap items-start justify-between gap-2"><p className="text-sm font-medium text-ink">Repair {index + 1} · {new Set(m.changes.map(c => c.row_id)).size} orders</p><div className="flex flex-wrap gap-1.5">{m.requires_review && <Badge tone="hold" size="sm">Second reviewer needed</Badge>}<Badge size="sm" tone={m.status === 'committed' ? 'good' : m.status === 'prepared' ? 'info' : 'hold'}>{m.status === 'prepared' ? 'Ready to apply' : m.status === 'committed' ? 'Applied' : m.status === 'stale' ? 'Out of date' : m.status === 'superseded' ? 'Superseded' : 'Rejected'}</Badge></div></div>
    <p className="mt-1 text-xs text-ink-3">Prepared {formatDateTime(m.created_at)}. Values come from the approved snapshot.</p>
    <ul className="mt-2 divide-y divide-line">{m.changes.map(c => <Change key={`${c.row_id}-${c.field}`} rowId={c.row_id} field={c.field} before={c.current_value} after={c.new_value} />)}</ul>
    <Technical><div className="mt-3 space-y-2 text-xs text-ink-3"><p className="break-all font-mono">{m.manifest_id} · {m.snapshot_id}</p><div className="flex flex-wrap gap-3"><Digest value={m.content_digest} label="manifest fingerprint" /><Digest value={m.snapshot_digest} label="snapshot digest" /></div><p>Authority epoch at preview: {m.preconditions.authority_epoch}</p><p className="break-all font-mono">{m.changes[0]?.source_path}</p><JsonRecord value={m} summary="Manifest, source paths and preconditions" /></div></Technical>
  </li>)}</ul>
}

function Receipts({ receipts, enforcement }: { receipts: ExecutionReceipt[]; enforcement: EnforcementFacts }) {
  if (!receipts.length) return <EmptyState compact title="No repair receipt yet" description="Only a committed repair produces a receipt. A blocked or prepared request has not changed data." />
  return <ul className="divide-y divide-line">{receipts.map((r, index) => <li key={r.operation_id} className="py-4 first:pt-0">
    <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-medium text-ink">Repair receipt {index + 1}</p><Badge size="sm" tone={r.result === 'committed' ? 'good' : 'bad'}>{r.result === 'committed' ? 'Committed' : 'Failed'}</Badge></div>
    <p className="mt-1 text-xs text-ink-3">{formatDateTime(r.committed_at ?? r.created_at)} · {isSimulatedEnforcement({ ...enforcement, enforcement_mode: r.enforcement_mode }) ? 'Simulated ArmorIQ' : 'Live ArmorIQ'}</p>
    <ul className="mt-2 divide-y divide-line">{r.changes.map(c => <Change key={`${c.row_id}-${c.field}`} rowId={c.row_id} field={c.field} before={c.before} after={c.after} />)}</ul>
    {!!r.checks.length && <Disclosure summary={`Protected checks at commit (${r.checks.filter(c => c.status === 'preserved' || c.status === 'repaired').length}/${r.checks.length} hold)`} className="mt-3"><ul className="space-y-2">{r.checks.map(c => <li key={c.check_id} className="text-[13px] text-ink-2"><span className="font-medium">{c.label}</span><span className="ml-2 text-xs text-ink-3">{INVARIANT_STATUS[c.status].label}</span><Technical><p className="mt-1 text-xs text-ink-3">{c.detail}</p></Technical></li>)}</ul></Disclosure>}
    <Technical><div className="mt-3 space-y-2 text-xs text-ink-3"><p className="break-all font-mono">{r.operation_id}</p><div className="flex flex-wrap gap-3"><Digest value={r.receipt_digest} label="receipt digest" /><Digest value={r.manifest_digest} label="repair fingerprint" /></div><p>{Object.entries(r.effect_counts).map(([key, value]) => `${key.replaceAll('_', ' ')}: ${value}`).join(' · ')}{r.sdk_version ? ` · SDK ${r.sdk_version}` : ''}</p><JsonRecord value={r} summary="Receipt, effects and protected evidence" /></div></Technical>
  </li>)}</ul>
}

function RawEvents({ events }: { events: RunEvent[] }) {
  if (!events.length) return <EmptyState compact title="No events recorded yet" description="The complete event stream appears here as the run progresses. Open any event to inspect its JSON." />
  return <ul className="divide-y divide-line">{events.map(e => <li key={e.seq} className="py-2"><JsonRecord value={e} summary={<EventSummary event={e} />} /></li>)}</ul>
}
function EventSummary({ event: e }: { event: RunEvent }) {
  return <span className="block min-w-0 text-left"><span className="block text-[13px] font-normal text-ink-2">{e.title}</span><span className="mt-1 block break-all font-mono text-[11px] font-normal text-ink-3">{e.seq} · {e.type}{hasTime(e.ts) ? ` · ${formatClock(e.ts)}` : ''}</span></span>
}

export function EvidenceDrawer({ open, onClose, runId, proof, decisions, manifests, receipts, events, enforcement, onExport, exporting, loading = false, error }: EvidenceDrawerProps) {
  const [tab, setTab] = useState<TabId>('decisions')
  const [mounted, setMounted] = useState(open)
  const titleId = useId()
  useEffect(() => setTab('decisions'), [runId])
  // Nested disclosures can keep the shared overlay's presence tree alive after its
  // exit finishes. Let its normal exit play, then release the entire portal tree.
  useEffect(() => {
    if (open) { setMounted(true); return }
    const timer = window.setTimeout(() => setMounted(false), DUR.base * 1000)
    return () => window.clearTimeout(timer)
  }, [open])
  const items: TabItem<TabId>[] = useMemo(() => [
    { id: 'decisions', label: 'Decisions', count: decisions.length },
    { id: 'manifests', label: 'Manifests', count: manifests.length },
    { id: 'receipts', label: 'Receipts', count: receipts.length },
    { id: 'raw', label: 'Raw events', count: events.length },
  ], [decisions.length, manifests.length, receipts.length, events.length])
  if (!open && !mounted) return null
  return <Drawer open={open} onClose={onClose} width="820px" title="Run evidence" description="Recorded decisions, exact repairs and proof of what stayed protected." footer={<div className="flex flex-wrap items-center justify-between gap-3"><p className="max-w-sm text-xs leading-relaxed text-ink-3">Download the complete JSON record. API keys, tokens and session cookies are excluded.</p><Button variant="primary" icon={<Download className="size-4" />} loading={exporting} onClick={onExport}>Export evidence</Button></div>}>
    <Technical><p className="mb-3 break-all font-mono text-xs text-ink-3">{runId} · The record is not edited after the fact.</p></Technical>
    {error ? <ErrorState compact error={error} title="Evidence could not load" /> : loading ? <div role="status" aria-label="Loading evidence"><SkeletonLines lines={5} /></div> : <>
      <section aria-labelledby={titleId} className="border-b border-line pb-5"><h3 id={titleId} className="text-[15px] font-semibold text-ink">What this run proves</h3><ul className="mt-3 space-y-3">{(proof.length ? proof : [{ tone: 'neutral' as const, text: 'No proof has been recorded yet. Decisions and receipts will appear as the agent works.' }]).map((line, index) => { const Icon = PROOF_ICON[line.tone]; return <li key={index} className="flex items-start gap-2.5 text-[13px] leading-relaxed text-ink-2"><Icon className="mt-0.5 size-4 shrink-0" style={{ color: TONE_COLOR[line.tone] }} aria-hidden /><div>{line.text}{line.technicalText && <Technical><p className="mt-1 text-xs text-ink-3">{line.technicalText}</p></Technical>}</div></li> })}</ul></section>
      <div className="mt-5 min-w-0"><Tabs items={items} value={tab} onChange={setTab} label="Evidence sections" /><div className="mt-4" role="tabpanel" aria-label={`${tab} evidence`}>
        {tab === 'decisions' && <Decisions rows={decisions} />}{tab === 'manifests' && <Manifests manifests={manifests} />}{tab === 'receipts' && <Receipts receipts={receipts} enforcement={enforcement} />}{tab === 'raw' && <><p className="mb-3 flex items-center gap-2 text-xs text-ink-3"><FileJson2 className="size-3.5" aria-hidden />Open an event to see its complete JSON.</p><RawEvents events={events} /></>}
      </div></div>
    </>}
  </Drawer>
}
