import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useAnimationControls } from 'motion/react'
import { Check, Database, Hourglass, PlugZap, X } from 'lucide-react'
import type { Layer } from '@/api/types'
import { Badge, Button, Digest, Loader } from '@/components/ui'
import { Technical } from '@/lib/detail'
import { DEFENSE_LAYERS, isSimulatedEnforcement, LAYERS, OUTCOMES, sourceLabel } from '@/lib/layers'
import { DUR, EASE, useMotionOK } from '@/lib/motion'
import { tint } from '@/lib/color'
import { toolLabel } from '@/lib/labels'
import { actionSentence, num, rec, type ProposalItem } from './model'
import { sourceNoteFor, type CardCtx } from './TimelineCards'
import { useMinWidth, useNow } from './hooks'
import { GATE_MEANING, gateResult, pendingGate, receiptFor, stopFor } from './stageModel'
import { OutcomeStage } from './OutcomeStage'

export function GateStage({ selected, pinned, onLive, ctx, replay, finished }: {
  selected?: ProposalItem; pinned: boolean; onLive: () => void; ctx: CardCtx; replay: boolean; finished: boolean
}) {
  const motionOK = useMotionOK()
  const compact = !useMinWidth(640)
  const controls = useAnimationControls()
  const track = useRef<HTMLDivElement>(null)
  const seen = useRef(new Set<string>())
  const plays = useRef(new Map<string, number>())
  const [width, setWidth] = useState(0)
  const [travelling, setTravelling] = useState(false)
  const [arrived, setArrived] = useState(-1)
  const [inspected, setInspected] = useState<Layer | 'endpoint' | null>(null)
  const decision = selected?.blocker ?? selected?.unavailable ?? (selected?.status === 'held' ? selected.decisions.find(d => !d.shadow && d.outcome === 'hold') : undefined)
    ?? selected?.decisions.find(d => !d.shadow && d.decisive)
    ?? selected?.decisions.filter(d => !d.shadow && d.outcome !== 'skipped').at(-1)
  const pending = !!selected && selected.status === 'pending' && !selected.blocker && !selected.unavailable
  const checking = pendingGate(selected, ctx.view)
  const outcomeVisible = finished && !pinned
  const held = selected?.status === 'held'
  const refused = selected?.status === 'stale' || selected?.status === 'rejected'
  const decidingLayer = stopFor(selected, ctx.view)
  const stopped = !!decidingLayer
  const receipt = receiptFor(selected, ctx.view)
  const readOnly = !!selected && ['inspect_snapshot', 'compare_current', 'prepare_repair_manifest', 'get_recovery_receipt'].includes(selected.tool)
  const layerIndex = decidingLayer ? DEFENSE_LAYERS.indexOf(decidingLayer) : -1
  const destination = stopped ? layerIndex : 5
  const outcome = decision ? OUTCOMES[decision.outcome] : undefined
  const color = refused || held ? 'var(--outcome-hold)' : stopped ? outcome && decision?.outcome !== 'allow' ? outcome.color : 'var(--outcome-block)' : receipt ? 'var(--outcome-allow)' : pending ? LAYERS[checking ?? 'armoriq'].color : 'var(--text-2)'
  const requestId = selected?.proposalId
  const decided = !!selected && !pending && (!!decision || selected.status !== 'pending')
  const note = selected ? sourceNoteFor(selected, ctx) : undefined
  const now = useNow((ctx.ticking || replay) && !finished && !pinned ? 100 : 0)
  const [settledAt, setSettledAt] = useState(() => Date.now())
  const latest = ctx.view.items.at(-1)
  const supervisorSent = latest?.kind === 'supervisor'
  const waitNote = latest?.kind === 'note' && (num(rec(latest.event.data).rate_limit_wait_s) !== undefined || /rate.?limit/i.test(`${latest.event.title} ${latest.event.detail}`)) ? latest : undefined
  const [waitNoteAt, setWaitNoteAt] = useState(() => Date.now())
  useEffect(() => { setSettledAt(Date.now()); setInspected(null) }, [requestId, selected?.status])
  useEffect(() => { setWaitNoteAt(Date.now()) }, [waitNote?.key])
  const waiting = !pinned && !finished && !pending && !held && !!ctx.plan && (supervisorSent || !!waitNote || !selected || now - settledAt >= 1200)
  const waitSeconds = waitNote ? num(rec(waitNote.event.data).rate_limit_wait_s) : undefined
  const providerWaitStarted = !replay && waitNote ? Date.parse(waitNote.ts) : waitNoteAt
  const countdown = waitSeconds === undefined ? undefined : Math.max(0, Math.ceil(waitSeconds - (now - providerWaitStarted) / 1000))
  const elapsed = Math.max(0, now - Date.parse(ctx.view.planRequestedAt ?? ctx.run?.created_at ?? ''))

  useEffect(() => {
    if (!track.current) return
    const observer = new ResizeObserver(entries => setWidth(entries[0].contentRect.width))
    observer.observe(track.current)
    return () => observer.disconnect()
  }, [requestId, finished, pinned, waiting])
  useEffect(() => { seen.current.clear(); plays.current.clear() }, [replay, ctx.run?.run_id])
  useEffect(() => {
    if (replay && ctx.view.proposals.length === 0) { seen.current.clear(); plays.current.clear() }
  }, [replay, ctx.view.proposals.length])
  useEffect(() => {
    if (!width) return
    let cancelled = false
    const x = (i: number) => i < 0 ? 0 : width * (i + .5) / 6 - 11
    controls.stop()
    if (!requestId || !decided) {
      controls.set({ x: x(checking ? DEFENSE_LAYERS.indexOf(checking) : 0), opacity: selected ? 1 : 0 })
      setArrived(-1)
      setTravelling(false)
      return
    }
    if (!motionOK || (!pinned && seen.current.has(requestId))) {
      controls.set({ x: x(destination), opacity: 1 })
      setArrived(destination)
      setTravelling(false)
      return
    }
    seen.current.add(requestId)
    plays.current.set(requestId, (plays.current.get(requestId) ?? 0) + 1)
    controls.set({ x: 0, opacity: 1 })
    setArrived(-1)
    setTravelling(true)
    void (async () => {
      for (let i = 0; i <= destination; i++) {
        await controls.start({ x: x(i), transition: { duration: .18, ease: EASE.out } })
        if (cancelled) return
        setArrived(i)
      }
      setTravelling(false)
    })()
    return () => { cancelled = true; controls.stop() }
  }, [requestId, decided, checking, destination, width, motionOK, pinned, controls, replay])

  const endpoint = stopped ? 'Not reached' : readOnly && selected?.status === 'executed' ? 'Read only · nothing written' : receipt ? 'Committed' : selected?.status === 'duplicate' ? 'Original receipt · no new write' : pending ? 'Not reached yet' : 'No commit recorded'
  const captionGate = inspected ?? decidingLayer ?? checking ?? (arrived >= 0 && arrived < 5 ? DEFENSE_LAYERS[arrived] : selected && !pending ? 'endpoint' : 'armoriq')
  const caption = captionGate === 'endpoint' ? `Endpoint · ${endpoint}` : `${LAYERS[captionGate].label} · ${gateResult(captionGate, selected, ctx).label}`
  const meaning = captionGate === 'endpoint' ? readOnly ? 'This request reads or prepares data; it does not write a repair.' : 'Only a recorded repair receipt confirms a database commit.' : GATE_MEANING[captionGate]

  const verdict = !selected ? (finished ? 'The run is finished. The recorded evidence is below.' : ctx.plan ? 'Plan signed. Waiting for the first request.' : isSimulatedEnforcement(ctx.enforcement) ? 'Binding the plan with simulated ArmorIQ.' : 'ArmorIQ is signing the recovery plan.')
    : pending ? finished ? 'No completed decision was recorded for this request.' : 'Checking this request before it can run.'
    : selected.status === 'held' ? 'Waiting for a second person. Nothing has changed yet.'
    : selected.blocker ? `${sourceLabel(selected.blocker)} stopped this request. Nothing changed.`
    : selected.unavailable ? 'Enforcement is unavailable. This request failed closed; nothing changed.'
    : selected.status === 'stale' || selected.status === 'rejected' ? 'This repair was not applied. The current decisions remain in place.'
    : selected.status === 'duplicate' ? 'The original receipt was returned. Nothing was written again.'
    : receipt ? 'The repair reached the database and committed in one transaction.'
    : readOnly && selected.status === 'executed' ? 'Read only · nothing written.'
    : 'No database commit is recorded for this request.'

  const stateKey = outcomeVisible ? 'outcome' : waiting ? waitNote ? 'rate-limit' : 'waiting' : `${requestId ?? 'signing'}-${selected?.status ?? ''}`
  const fade = { duration: motionOK ? DUR.base : 0, ease: EASE.out }
  return <section aria-label={outcomeVisible ? 'Run outcome' : 'Request through the defence gates'} data-gate-stage data-proposal={requestId ?? ''} data-pending={pending && !outcomeVisible || undefined} data-gate-state={outcomeVisible ? 'finished' : waiting ? 'waiting' : travelling ? 'in-flight' : decided ? 'decided' : selected ? 'in-flight' : 'waiting'} data-arrived-gate={arrived} data-gate-plays={requestId ? plays.current.get(requestId) ?? 0 : 0}
    className={`grid h-[380px] ${compact && outcomeVisible ? 'grid-rows-[112px_0px_minmax(140px,1fr)]' : 'grid-rows-[80px_94px_minmax(140px,1fr)]'} overflow-hidden rounded-2xl border border-line bg-raised px-4 py-4 sm:h-[360px] sm:grid-rows-[60px_140px_minmax(112px,1fr)] sm:px-6 sm:py-5`}>
    <div className="relative min-h-0">
    <AnimatePresence initial={false}>
    <motion.div key={stateKey} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, pointerEvents: 'none' }} transition={fade} className="absolute inset-0 overflow-auto">
    {outcomeVisible ? <OutcomeStage ctx={ctx} replay={replay} heading /> : <div className="flex items-start justify-between gap-3 sm:gap-4">
      <div className="min-w-0">
        <h2 className="text-base font-semibold leading-snug tracking-tight sm:text-xl">{waiting ? waitNote ? `Waiting for the model provider (rate limit)${countdown !== undefined ? `, about ${countdown} s` : ''}` : ctx.run?.planner_kind === 'harness' ? 'Nemesis is deciding the next step' : 'Athena is deciding the next step' : selected ? actionSentence(selected.tool, selected.args, ctx.action) : 'Before the agent can act'}</h2>
        <p className="mt-1 text-xs text-ink-2">{waiting ? supervisorSent ? 'Supervisor check sent. Waiting for the agent’s next step.' : 'No new request is being checked.' : selected ? note ? 'Instruction matches the untrusted snapshot note' : selected.source === 'boundary_harness' ? 'Boundary test probe' : selected.source === 'operator' ? 'Operator request' : selected.source === 'mcp' ? 'Request from an MCP client' : 'Request from the agent’s own plan' : 'The plan must be signed before any request can run.'}{replay ? ' · Recorded replay' : ''}{pinned ? ' · Pinned step' : ''}</p>
        {stopped && decidingLayer === 'runtime' && <p className="mt-1 text-xs text-ink-2">Stopped by the runtime before the defence gates.</p>}
      </div>
      {pinned && <Button size="sm" variant="secondary" onClick={onLive}>{finished ? 'Back to outcome' : 'Back to live'}</Button>}
    </div>}
    </motion.div>
    </AnimatePresence>
    </div>
    <motion.div ref={track} animate={{ opacity: 1 }} transition={fade} className={`relative h-[78px] sm:h-[120px] ${compact && outcomeVisible ? 'invisible pointer-events-none' : ''}`} aria-hidden={compact && outcomeVisible || undefined} aria-label="Five gates, then the endpoint">
      <div className="absolute inset-x-[8.33%] top-[27px] h-px bg-line-strong" aria-hidden />
      <div className="relative grid grid-cols-6">
        {DEFENSE_LAYERS.map((id, i) => {
          const layer = LAYERS[id]; const Icon = layer.icon
          const result = gateResult(id, selected, ctx)
          const shadow = result.shadow
          const reached = arrived >= i && (!stopped || i <= destination)
          return <div key={id} className="min-w-0 text-center" data-gate={id} data-shadow={shadow || undefined}>
            <button type="button" aria-label={`${layer.label}: ${GATE_MEANING[id]} ${result.label}`} aria-pressed={inspected === id} onClick={() => setInspected(id)} className="relative mx-auto grid size-11 place-items-center rounded-xl border bg-raised transition-colors hover:bg-surface-2 active:bg-surface-3 sm:size-14" style={{ color: layer.color, borderColor: reached || inspected === id ? tint(layer.color, 65) : 'var(--border)', background: shadow ? `repeating-linear-gradient(135deg, ${tint(layer.color, 14)} 0px, ${tint(layer.color, 14)} 3px, var(--bg-raised) 3px, var(--bg-raised) 7px)` : undefined }}>
              <Icon className="size-5" aria-hidden />
              {result.pending && !waiting && !outcomeVisible && <motion.span data-pending-ring aria-hidden className="pointer-events-none absolute -inset-1 rounded-2xl border" style={{ borderColor: layer.color }} animate={motionOK ? { opacity: [.4, 1, .4] } : { opacity: 1 }} transition={{ duration: 1.5, repeat: motionOK ? Infinity : 0, ease: EASE.inOut }} />}
            </button>
            <p className="mt-2 text-[11px] font-medium leading-tight text-ink-2 sm:text-xs">{layer.short}</p>
            {!compact && <p className="mt-1 px-0.5 text-xs leading-tight text-ink-2" style={{ color: id === 'postgres' && receipt ? 'var(--outcome-allow)' : undefined }}>{result.label}</p>}
          </div>
        })}
        <div className="text-center">
          <button type="button" aria-label={`Endpoint: ${endpoint}`} aria-pressed={inspected === 'endpoint'} onClick={() => setInspected('endpoint')} className="mx-auto grid size-11 place-items-center rounded-xl border bg-raised transition-colors hover:bg-surface-2 active:bg-surface-3 sm:size-14" style={{ borderColor: arrived === 5 ? tint(color, 65) : 'var(--border)', color: arrived === 5 ? color : 'var(--text-3)' }}><Database className="size-5" aria-hidden /></button>
          <p className="mt-2 text-[11px] font-medium text-ink-2 sm:text-xs">Endpoint</p>
          {!compact && <p className="mt-1 text-xs text-ink-2">{endpoint}</p>}
        </div>
      </div>
      <motion.div aria-hidden className="pointer-events-none absolute left-0 top-[17px] z-10 grid size-[22px] place-items-center rounded-full border-2 bg-raised"
        initial={false} animate={controls} style={{ color: travelling ? 'var(--text)' : color, borderColor: !travelling && stopped && decidingLayer ? LAYERS[decidingLayer].color : color, background: !travelling && stopped ? tint(color, 25) : 'var(--bg-raised)' }}>
        {!travelling && selected ? selected.blocker ? <X className="size-3.5" /> : pending || selected.status === 'held' ? <Hourglass data-pending-glyph={pending || undefined} className="size-3" /> : selected.unavailable ? <PlugZap className="size-3" /> : <Check className="size-3" /> : <span className="size-1.5 rounded-full bg-current" />}
      </motion.div>
    </motion.div>
    <div className="relative min-h-[140px] border-t border-line sm:min-h-[112px]">
    <AnimatePresence initial={false}>
    <motion.div key={stateKey} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, pointerEvents: 'none' }} transition={fade} className={`absolute inset-0 ${compact && outcomeVisible ? 'overflow-visible' : 'overflow-auto overscroll-contain'} pt-2 sm:pt-3`} tabIndex={compact && outcomeVisible ? undefined : 0} aria-label="Stage details">
    {outcomeVisible ? <OutcomeStage ctx={ctx} replay={replay} compact={compact} /> : <>
    <div className="flex items-start gap-2.5" role="status" aria-live="polite">
      {(waiting || !selected && !ctx.plan) && <Loader size="sm" label={waiting ? 'Waiting for the next request' : 'Signing the plan'} />}
      <div className="min-w-0">
        {waiting ? <><p className="text-[13px] tabular text-ink-2">{Math.max(0, (now - settledAt) / 1000).toFixed(1)} s since the last request settled</p>{selected && <p className="mt-2 text-[13px] leading-relaxed text-ink-2">Last request: {actionSentence(selected.tool, selected.args, ctx.action)} · {verdict}</p>}</> : <><p className="text-[13px] font-medium leading-relaxed sm:text-sm" style={{ color: selected ? color : 'var(--text)' }}>{verdict}</p><p className="mt-2 text-[13px] font-medium leading-relaxed text-ink" aria-live="polite">{caption}</p><p className="mt-1 max-w-[75ch] text-[13px] leading-relaxed text-ink-2">{meaning}</p></>}
        {!selected && !ctx.plan && ctx.ticking && Number.isFinite(elapsed) && <p className="mt-1 text-xs tabular text-ink-3">{(elapsed / 1000).toFixed(1)} s elapsed</p>}
      </div>
    </div>
    {!selected && <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Allowed plan steps">{(ctx.plan?.steps ?? ctx.grant?.allowed_tools ?? []).map(tool => <li key={tool}><Badge size="sm" color="var(--layer-armoriq)" dashed={!ctx.plan}>{toolLabel(tool)}</Badge></li>)}</ul>}
    <Technical><div className="mt-4 space-y-3 border-t border-line pt-3 text-xs text-ink-2">
      <p>ArmorIQ binds tool names, VeerIQ binds arguments.</p>
      <p>{LAYERS[captionGate === 'endpoint' ? 'postgres' : captionGate].description}</p>
      {(['grant', 'domain'] as const).map(id => gateResult(id, selected, ctx).inferred && <p key={id}>{LAYERS[id].label}: checked in order; no refusal (allow results are not stored as separate records).</p>)}
      {ctx.plan?.plan_hash && <div className="flex flex-wrap items-center gap-2">Plan hash <Digest value={ctx.plan.plan_hash} label="plan hash" /></div>}
      {selected?.decisions.map(d => <div key={d.decision_id} className="space-y-1 break-words">
        <p>{sourceLabel(d)} · {d.source} · {d.latency_ms ?? 'unmeasured'} ms · decisive: {String(d.decisive)} · shadow: {String(d.shadow)}</p>
        <p>Matched policy: {d.sponsor?.matched_policy ?? 'none reported'} · Raw reason: {d.reason}</p>
        <p className="font-mono text-[11px]">{d.decision_id}</p>
      </div>)}
    </div></Technical>
    </>}
    </motion.div>
    </AnimatePresence>
    </div>
    {travelling && <span className="sr-only">Request travelling through the gates</span>}
  </section>
}
