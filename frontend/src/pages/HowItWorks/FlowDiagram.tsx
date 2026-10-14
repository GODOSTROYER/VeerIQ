import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { Ban, Check, RotateCcw } from 'lucide-react'
import { Badge, Button, Disclosure, Tabs } from '@/components/ui'
import { Technical } from '@/lib/detail'
import { DEFENSE_LAYERS, LAYERS } from '@/lib/layers'
import { T, useMotionOK } from '@/lib/motion'
import { cn } from '@/lib/cn'

type Mode = 'allowed' | 'blocked'
const X = [100, 260, 420, 580, 740, 910]
const CAPTIONS = [
  'ArmorIQ confirms this tool is in the signed plan and policy allows it.',
  'VeerIQ checks the tenant, records, fields and snapshot against the grant.',
  'Snapshot values only. Deletions, holds, newer edits and row versions stay protected.',
  'This repair is under the review threshold. A higher-value payload would pause for a second person.',
  'PostgreSQL re-checks state and writes through a role limited to the granted columns.',
  'The repair lands in one transaction. A receipt saves before and after values, checks and digests.',
]
const MEANINGS = [
  'Is this action in the signed plan?',
  'Is it limited to the approved company, orders and fields?',
  'Will today’s decisions and newer edits stay protected?',
  'Does this amount need a second person’s approval?',
  'Can this database role write only the permitted fields?',
  'Save the repair once, with a receipt of what changed.',
]
export function FlowDiagram() {
  const motionOK = useMotionOK()
  const [mode, setMode] = useState<Mode>('allowed')
  const [step, setStep] = useState(-1)
  const last = mode === 'blocked' ? 0 : 5
  useEffect(() => { setStep(-1) }, [mode])
  const playing = false
  const blocked = mode === 'blocked' && step >= 0
  const finished = !playing && step >= last
  const color = blocked ? 'var(--outcome-block)' : finished ? 'var(--outcome-allow)' : 'var(--text)'
  const outcome = (i: number) => blocked ? i === 0 ? 'Stopped' : i === 5 ? 'No write' : 'Not reached' : i === 5 ? finished ? 'Repaired' : 'Waiting' : step >= i ? i === 3 ? 'Review not required' : 'Passed' : 'Waiting'
  return <div className="space-y-5" data-flow-mode={mode} data-flow-step={step} data-flow-playing={playing}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <Tabs className="max-md:w-full max-md:[&>button]:h-auto max-md:[&>button]:min-h-11 max-md:[&>button]:min-w-0 max-md:[&>button]:flex-1 max-md:[&>button]:shrink max-md:[&>button]:px-2" label="Choose a request" value={mode} onChange={setMode} items={[{ id: 'allowed', label: 'Legitimate repair' }, { id: 'blocked', label: 'Poisoned instruction' }]} />
      <Button className="max-md:min-h-11" variant="ghost" size="sm" icon={<RotateCcw className="size-4" />} onClick={() => setStep(-1)}>Restart explanation</Button>
    </div>
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
      <p className="font-medium text-ink">{mode === 'allowed' ? 'Repair two Atlas orders from the approved snapshot' : 'Restore a revoked account, as the planted note instructs'}</p>
      <Badge tone={blocked ? 'bad' : finished ? 'good' : 'neutral'}>{blocked ? 'Stopped by ArmorIQ' : finished ? 'Repair explained' : step < 0 ? 'Ready when you are' : `Check ${step + 1} of 5`}</Badge>
    </div>
    <p className="text-[13px] leading-relaxed text-ink-2">Before either request: Nova grants one narrow task → ArmorIQ signs its allowed tools → the agent proposes an action.</p>
    <div className="hidden rounded-xl bg-sunken px-3 py-4 md:block" aria-label="Five independent gates followed by the database">
      <svg viewBox="0 0 1000 140" className="block w-full" role="img" aria-label={blocked ? 'Request clamped at ArmorIQ; no database write' : finished ? 'Request passed all five gates and reached the database' : 'Request travelling through the independent gates'}>
        <path d="M20 70 H950" stroke="var(--border-strong)" strokeWidth="3" />
        {DEFENSE_LAYERS.map((layer,i) => {
          const reached = step >= i && !(mode === 'blocked' && i > 0)
          return <g key={layer} transform={'translate(' + X[i] + ' 70)'}>
            <path d="M-21 -36 H-31 V36 H-21 M21 -36 H31 V36 H21" fill="none" stroke={LAYERS[layer].color} strokeWidth={blocked && i === 0 ? 5 : 3} opacity={reached ? 1 : 0.5} />
            {reached && !(blocked && i === 0) && step >= i && <path d="M-9 -3 L-2 4 L10 -8" stroke="var(--outcome-allow)" strokeWidth="3" fill="none" />}
          </g>
        })}
        <g transform="translate(910 70)" stroke={finished && !blocked ? 'var(--outcome-allow)' : 'var(--text-3)'} strokeWidth="2.5" fill="var(--bg-raised)">
          <path d="M-24 -16 V16 C-24 28 24 28 24 16 V-16" /><ellipse rx="24" ry="10" cy="-16" /><path d="M-24 0 C-24 12 24 12 24 0" fill="none" />
        </g>
        <motion.g initial={false} animate={{ x: step < 0 ? 20 : X[step] ?? 910, opacity: 1 }} transition={motionOK ? { ...T.fast, duration: 0.45 } : { duration: 0 }} data-request-token>
          <circle cy="70" r="10" fill={color} stroke={blocked ? 'var(--layer-armoriq)' : 'var(--bg-sunken)'} strokeWidth={blocked ? 5 : 3} />
          {blocked && <path d="M-17 52 V88 M17 52 V88" stroke="var(--outcome-block)" strokeWidth="5" />}
        </motion.g>
      </svg>
      <ol className="grid grid-cols-6 gap-1 text-center text-[13px] font-medium leading-tight">
        {DEFENSE_LAYERS.map((layer,i) => <li key={layer} className={cn('min-w-0', blocked && i > 0 ? 'text-ink-3' : 'text-ink-2')}><span style={{ color: LAYERS[layer].color }}>{LAYERS[layer].short}</span><span className="mt-1 block font-normal">{outcome(i)}</span></li>)}
        <li className="text-ink-2">Database<span className="mt-1 block font-normal">{outcome(5)}</span></li>
      </ol>
    </div>
    <div className="relative rounded-xl bg-sunken p-3 md:hidden" aria-label="A request travels downward through five gates to the database">
      <svg width="48" height="684" className="absolute left-3 top-3" aria-hidden="true">
        <path d="M24 4 V650" stroke="var(--border-strong)" strokeWidth="2" />
        {DEFENSE_LAYERS.map((layer,i) => <g key={layer} transform={`translate(24 ${i * 114 + 28})`}>
          <path d="M-12 -20 H-20 V20 H-12 M12 -20 H20 V20 H12" fill="none" stroke={LAYERS[layer].color} strokeWidth={blocked && i === 0 ? 4 : 2} opacity={step >= i && !(blocked && i > 0) ? 1 : 0.5} />
        </g>)}
        <g transform="translate(24 598)" stroke={finished && !blocked ? 'var(--outcome-allow)' : 'var(--text-3)'} strokeWidth="2" fill="var(--bg-raised)">
          <path d="M-16 -10 V10 C-16 18 16 18 16 10 V-10" /><ellipse rx="16" ry="6" cy="-10" /><path d="M-16 0 C-16 8 16 8 16 0" fill="none" />
        </g>
        <motion.g initial={false} animate={{ y: step < 0 ? 4 : step * 114 + 28 }} transition={motionOK ? { ...T.fast, duration: 0.45 } : { duration: 0 }} data-mobile-request-token>
          <circle cx="24" r="8" fill={color} stroke={blocked ? 'var(--layer-armoriq)' : 'var(--bg-sunken)'} strokeWidth="3" />
          {blocked && <path d="M12 -14 H36 M12 14 H36" stroke="var(--outcome-block)" strokeWidth="4" />}
        </motion.g>
      </svg>
      <ol className="pl-16 text-[13px] leading-relaxed">
        {[...DEFENSE_LAYERS, 'database' as const].map((layer,i) => <li key={layer} className="min-h-[114px] py-2" aria-current={step === i ? 'step' : undefined}>
          <p className="font-semibold" style={{ color: layer === 'database' ? 'var(--text)' : LAYERS[layer].color }}>{layer === 'database' ? 'Database & receipt' : LAYERS[layer].label}</p>
          <p className="mt-1 text-ink-2">{MEANINGS[i]}</p>
          <p className={cn('mt-1 font-medium', blocked && i === 0 ? 'text-block' : !blocked && (step > i || finished && i === 5) ? 'text-allow' : 'text-ink-3')}>{outcome(i)}</p>
        </li>)}
      </ol>
    </div>
    <div className="flex min-h-20 items-start gap-3 border-t border-line pt-4" aria-live="polite">
      {blocked ? <Ban className="mt-0.5 size-5 shrink-0 text-block" /> : finished ? <Check className="mt-0.5 size-5 shrink-0 text-allow" /> : null}
      <p className="max-w-[72ch] text-[15px] leading-relaxed text-ink">{blocked ? 'ArmorIQ clamps the request at the first gate: restoring access is outside the signed plan. The handler never runs. Nothing changes.' : step < 0 ? 'The agent’s request is only a proposal. It must cross every gate before it can change data.' : CAPTIONS[step]}</p>
    </div>
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="secondary" disabled={step < 0} onClick={() => setStep(n => Math.max(-1, n - 1))}>Previous step</Button>
      <Button variant="primary" disabled={step >= last} onClick={() => setStep(n => Math.min(last, n + 1))}>{step < 0 ? 'Start request' : step === 4 ? 'Show repair outcome' : 'Next check'}</Button>
      <p className="text-xs text-ink-3">{finished ? 'Explanation complete. Restart or review a previous step.' : 'Take your time. Nothing advances until you choose the next step.'}</p>
    </div>
    <Technical><Disclosure summary="Read every gate’s responsibility">
      <ul className="space-y-3">{DEFENSE_LAYERS.map(layer => <li key={layer} className="text-[13px] leading-relaxed text-ink-2"><strong style={{ color: LAYERS[layer].color }}>{LAYERS[layer].label}: </strong>{LAYERS[layer].description}</li>)}</ul>
      <p className="mt-4 text-[13px] text-ink-2">Illustrated grant: Atlas only; orders O-2041 and O-2042; three fields; one commit; five recovery tools. The poisoned proposal is restore_access_grant for svc-legacy-sync. ArmorIQ binds the tool name; VeerIQ binds argument values.</p>
    </Disclosure></Technical>
    <p className="text-xs leading-relaxed text-ink-3">An illustration of the design, not a live model run. Each gate can refuse a request; the first stop is final. Real runs retain each decision and its source in the workspace.</p>
  </div>
}
