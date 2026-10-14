import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowDown, Ban, Check, ChevronDown, CircleDot, FileDiff, FileWarning, Layers, RotateCcw, Settings2, ShieldCheck, Siren, TriangleAlert, UserCheck, type LucideIcon } from 'lucide-react'
import { AnimatedItem, AnimatedList, Collapse } from '@/components/motion'
import { Badge, Button, Disclosure } from '@/components/ui'
import { Technical } from '@/lib/detail'
import { isSimulatedEnforcement, LAYERS, OUTCOMES, sourceLabel } from '@/lib/layers'
import { humanReason, NOTE_FOOTER } from '@/lib/reasons'
import { useMotionOK } from '@/lib/motion'
import { actionSentence, scrubPlaceholders, type TimelineItem } from './model'
import { ApprovalCard, CommitCard, DuplicateCard, ExternalCard, LooseDecision, ManifestCard, PlanCard, PlanSigningCard, PlanFailedCard, ProposalCard, RejectedCard, ReplanDivider, UntrustedNoteCard, type CardCtx } from './TimelineCards'

interface RowInfo { Icon: LucideIcon; color: string; sentence: string; outcome?: string; why?: string }
function rowInfo(item: TimelineItem, ctx: CardCtx): RowInfo {
  const neutral = 'var(--text-3)', allow = 'var(--outcome-allow)', block = 'var(--outcome-block)', hold = 'var(--outcome-hold)'
  switch (item.kind) {
    case 'proposal': {
      const d = item.blocker ?? item.unavailable ?? item.decisions.find(d => !d.shadow && d.outcome === 'hold') ?? item.decisions.filter(d => !d.shadow && d.outcome !== 'skipped').at(-1)
      const stopped = !!item.blocker
      return { Icon: stopped ? Ban : item.status === 'held' ? UserCheck : item.status === 'executed' ? Check : CircleDot, color: stopped ? block : d ? OUTCOMES[d.outcome].color : neutral,
        sentence: actionSentence(item.tool, item.args, ctx.action), outcome: d ? `${stopped ? 'Stopped by' : d.outcome === 'allow' ? 'Allowed by' : OUTCOMES[d.outcome].label + ' ·'} ${LAYERS[d.layer].short}${d.simulated ? ' (simulated)' : ''}` : item.status === 'pending' ? 'Checking' : item.status,
        why: stopped ? humanReason(item.blocker!, item.tool) : item.unavailable ? humanReason(item.unavailable, item.tool) : undefined }
    }
    case 'plan': {
      const simulated = isSimulatedEnforcement(ctx.enforcement)
      return { Icon: ShieldCheck, color: 'var(--layer-armoriq)', sentence: simulated ? 'Plan bound by simulated ArmorIQ' : 'ArmorIQ signed the allowed actions', outcome: simulated ? 'Simulated' : 'Signed plan' }
    }
    case 'planRequest': return { Icon: ShieldCheck, color: 'var(--layer-armoriq)', sentence: isSimulatedEnforcement(ctx.enforcement) ? 'Binding the plan (simulated)' : 'ArmorIQ is signing the plan', outcome: 'Waiting' }
    case 'planFailed': return { Icon: Ban, color: block, sentence: 'The plan could not be signed', outcome: 'Failed closed', why: item.event.detail }
    case 'note': return { Icon: CircleDot, color: neutral, sentence: scrubPlaceholders(item.event.detail?.trim() || item.event.title) }
    case 'supervisor': return { Icon: Settings2, color: neutral, sentence: 'Automatic supervisor check', outcome: 'System' }
    case 'untrusted': return { Icon: FileWarning, color: hold, sentence: 'The agent read an untrusted note in the snapshot', outcome: 'Untrusted', why: NOTE_FOOTER }
    case 'manifest': return { Icon: FileDiff, color: 'var(--layer-grant)', sentence: `Repair prepared for ${Array.from(new Set(item.manifest.changes.map(c => c.row_id))).join(', ')}`, outcome: item.manifest.requires_review ? 'Needs second person' : 'Prepared' }
    case 'approval': return { Icon: UserCheck, color: item.approval.status === 'approved' ? allow : hold, sentence: item.approval.status === 'pending' ? 'Waiting for a second person to approve this repair' : `${ctx.nameOf(item.approval.decided_by)}: repair ${item.approval.status.replaceAll('_', ' ')}`, outcome: 'Second reviewer' }
    case 'commit': return { Icon: Check, color: allow, sentence: `Repaired ${Array.from(new Set(item.receipt.changes.map(c => c.row_id))).join(', ')} in one transaction`, outcome: 'Committed · Postgres' }
    case 'rejected': return { Icon: TriangleAlert, color: hold, sentence: 'The prepared repair was refused before writing', outcome: 'No change', why: item.event.detail }
    case 'duplicate': return { Icon: Layers, color: neutral, sentence: 'The same request returned its original receipt', outcome: 'No second write' }
    case 'replan': return { Icon: RotateCcw, color: neutral, sentence: 'The agent revised its plan after the refusal', outcome: 'Replanning' }
    case 'external': return { Icon: Siren, color: hold, sentence: item.event.title, outcome: 'Authority changed' }
    case 'decision': return { Icon: LAYERS[item.decision.layer].icon, color: OUTCOMES[item.decision.outcome].color, sentence: `${sourceLabel(item.decision)} ${item.decision.shadow ? 'would also have ' : ''}${OUTCOMES[item.decision.outcome].verb} this request`, outcome: LAYERS[item.decision.layer].short, why: item.decision.outcome === 'block' ? humanReason(item.decision) : undefined }
    case 'finish': return { Icon: ShieldCheck, color: allow, sentence: 'The run finished; its certificate is below', outcome: 'Recorded' }
  }
}
function details(item: TimelineItem, ctx: CardCtx): ReactNode {
  switch (item.kind) {
    case 'proposal': return <ProposalCard item={item} ctx={ctx} />
    case 'plan': return <PlanCard plan={item.plan} event={item.event} latencyMs={item.latencyMs} matchedPolicies={item.matchedPolicies} simulated={isSimulatedEnforcement(ctx.enforcement)} />
    case 'planRequest': return <PlanSigningCard ctx={ctx} requestedAt={item.ts} />
    case 'planFailed': return <PlanFailedCard event={item.event} />
    case 'untrusted': return item.annotations.map(a => <UntrustedNoteCard key={a.annotationId} annotation={a} ctx={ctx} />)
    case 'manifest': return <ManifestCard manifest={item.manifest} status={item.status} />
    case 'approval': return <ApprovalCard approval={item.approval} ctx={ctx} />
    case 'commit': return <CommitCard receipt={item.receipt} />
    case 'rejected': return <RejectedCard event={item.event} />
    case 'duplicate': return <DuplicateCard event={item.event} />
    case 'replan': return <ReplanDivider event={item.event} />
    case 'external': return <ExternalCard event={item.event} />
    case 'decision': return <LooseDecision decision={item.decision} />
    case 'supervisor': return <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink-2">{scrubPlaceholders(item.event.detail || item.event.title)}</p>
    case 'note': case 'finish': return null
  }
}
function FeedRow({ item, ctx, newest }: { item: TimelineItem; ctx: CardCtx; newest: boolean }) {
  const [open, setOpen] = useState(false)
  const info = rowInfo(item, ctx); const { Icon } = info
  const relatedId = item.kind === 'proposal' ? item.proposalId : item.kind === 'untrusted' ? item.toolProposalId : item.kind === 'approval' ? item.approval.proposal_id : item.kind === 'decision' ? item.decision.proposal_id : 'event' in item ? item.event.proposal_id : undefined
  const select = () => { setOpen(v => !v); if (relatedId) ctx.onSelect(relatedId) }
  const origin = Date.parse(ctx.run?.created_at ?? item.ts)
  const seconds = Math.max(0, Math.round((Date.parse(item.ts) - origin) / 1000))
  return <AnimatedItem id={item.kind === 'proposal' ? `proposal-${item.proposalId}` : item.kind === 'untrusted' ? `note-${item.annotations[0]?.annotationId}` : `feed-${item.key}`} data-feed-row={item.key} data-newest={newest || undefined} highlight={newest ? info.color : undefined} className="border-b border-line last:border-b-0">
    <button type="button" onClick={select} aria-expanded={open} aria-controls={`detail-${item.key}`} className="group flex w-full items-start gap-3 rounded-lg px-1 py-3 text-left transition-colors hover:bg-surface-2 active:bg-surface-3" aria-pressed={relatedId ? ctx.selectedId === relatedId : undefined}>
      <Icon className="mt-0.5 size-4 shrink-0" style={{ color: info.color }} aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] leading-relaxed text-ink" style={item.kind === 'note' && !open ? { display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' } : undefined}>{info.sentence}</span>
        {info.why && <span className="mt-0.5 line-clamp-1 text-xs leading-relaxed text-ink-2">{info.why}</span>}
        {info.outcome && <span className="mt-1 inline-flex sm:hidden"><Badge color={info.color} size="sm">{info.outcome}</Badge></span>}
      </span>
      <span className="hidden shrink-0 sm:inline-flex">{info.outcome && <Badge color={info.color} size="sm">{info.outcome}</Badge>}</span>
      <time dateTime={item.ts} title={item.ts} className="mt-0.5 shrink-0 text-[10px] tabular text-ink-3">+{seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`}</time>
      <ChevronDown className={`mt-0.5 size-3.5 shrink-0 text-ink-3 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
    </button>
    <Technical>{item.kind === 'proposal' && <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 pl-8 text-[11px] text-ink-3"><span className="break-all font-mono">{item.proposalId}</span>{item.decisions.map(d => <span key={d.decision_id}>{sourceLabel(d)} · {d.latency_ms ?? 'unmeasured'} ms</span>)}{ctx.plan?.plan_hash && <span className="break-all font-mono">Plan {ctx.plan.plan_hash}</span>}</div>}</Technical>
    <Technical>{item.kind === 'supervisor' && <p className="mb-2 whitespace-pre-wrap pl-8 text-xs leading-relaxed text-ink-2">{scrubPlaceholders(item.event.detail || item.event.title)}</p>}</Technical>
    <Collapse open={open} id={`detail-${item.key}`}><div className="space-y-3 pb-4 pl-7">
      {details(item, ctx)}
      <Technical><Disclosure summary="Full recorded step"><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-ink-2">{JSON.stringify(item, null, 2)}</pre></Disclosure></Technical>
    </div></Collapse>
  </AnimatedItem>
}
export function Timeline({ items, ctx, active }: { items: TimelineItem[]; ctx: CardCtx; active: boolean }) {
  const root = useRef<HTMLDivElement>(null)
  const previousCount = useRef(items.length)
  const [unseen, setUnseen] = useState(0)
  const motionOK = useMotionOK()
  useEffect(() => {
    const added = Math.max(0, items.length - previousCount.current)
    previousCount.current = items.length
    if (!active || !items.length) { setUnseen(0); return }
    const newest = root.current?.querySelector('[data-newest]')
    if (!newest) return
    const box = newest.getBoundingClientRect()
    if (added && (box.bottom > window.innerHeight || box.top < 0)) setUnseen(n => n + added)
    const observer = new IntersectionObserver(entries => { if (entries[0]?.isIntersecting && entries[0].intersectionRatio > .9) setUnseen(0) }, { threshold: [.9, 1] })
    observer.observe(newest)
    return () => observer.disconnect()
  }, [items.length, active])
  return <div ref={root} style={{ overflowAnchor: 'none' }}>
    <p className="mb-2 text-xs text-ink-3">Times are relative to the start. Open a request to pin it above.</p>
    <AnimatedList aria-label="Agent timeline">{items.map((item, i) => <FeedRow key={item.key} item={item} ctx={ctx} newest={i === items.length - 1} />)}</AnimatedList>
    {unseen > 0 && <div className="pointer-events-none fixed inset-x-0 bottom-5 z-30 flex justify-center"><Button size="sm" variant="secondary" className="pointer-events-auto" icon={<ArrowDown className="size-3.5" />} onClick={() => { root.current?.querySelector('[data-newest]')?.scrollIntoView({ behavior: motionOK ? 'smooth' : 'auto', block: 'center' }); setUnseen(0) }}>{unseen} new {unseen === 1 ? 'step' : 'steps'}</Button></div>}
  </div>
}
