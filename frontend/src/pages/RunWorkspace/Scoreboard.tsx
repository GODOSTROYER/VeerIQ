import type { ReactNode } from 'react'
import { motion } from 'motion/react'
import { Check, ShieldAlert } from 'lucide-react'
import type { AppState, InvariantCheck, RunMetrics, TaskGrant } from '@/api/types'
import { formatMoney } from '@/lib/format'
import { toolLabel } from '@/lib/labels'
import { isSimulatedEnforcement, LAYERS, type EnforcementFacts } from '@/lib/layers'
import { Technical } from '@/lib/detail'
import { T, useMotionOK } from '@/lib/motion'
import { NumberRoll } from '@/components/motion'
import { Skeleton } from '@/components/ui'
import type { RunView } from './model'
import { decisionChecks, isHeld, recordedProtectedChecks, repairedOrders, targetOrders } from './proof'

function Promise({ label, value, caption, fill, color = 'var(--text-3)', alert = false }: { label: string; value: ReactNode; caption: string; fill: number; color?: string; alert?: boolean }) {
  const motionOK = useMotionOK()
  return <div className="min-w-0 px-4 py-3" role={alert ? 'alert' : undefined}>
    <div className="flex min-h-6 flex-wrap items-center justify-between gap-x-2 gap-y-1 text-[13px]">
      <h2 className="font-medium text-ink-2">{label}</h2>
      <span className="tabular inline-flex items-center gap-1 font-semibold text-ink" style={{ color }}>{value}</span>
    </div>
    <p className="mt-1 min-h-8 text-xs leading-snug text-ink-3">{caption}</p>
    <div className="mt-2 h-0.5 overflow-hidden rounded-full bg-surface-3" aria-hidden>
      <motion.div className="h-full origin-left" style={{ background: color }} initial={false} animate={{ scaleX: Math.max(0, Math.min(1, fill)) }} transition={motionOK ? T.base : { duration: 0 }} />
    </div>
  </div>
}

function Fraction({ n, of }: { n: number; of: number }) {
  return <><NumberRoll value={n} /><span className="font-normal text-ink-3">/ {of}</span></>
}

export interface ScoreboardProps {
  view: RunView
  /** Shared facts behind every "Live" or "Simulated" label on the page. */
  enforcement: EnforcementFacts
  grant: TaskGrant | undefined
  checks: InvariantCheck[] | undefined
  appState: AppState | undefined
  metrics: RunMetrics | undefined
  live: boolean
  /** Suppress current/final state until the recorded verification reaches this replay prefix. */
  replaying?: boolean
  /** Current demo checks are not evidence for a run from an older generation. */
  generationMismatch?: boolean
  workflow?: string
}

export function Scoreboard({ view, enforcement, grant, checks, appState, metrics, live, replaying = false, generationMismatch = false, workflow }: ScoreboardProps) {
  const target = targetOrders(grant)
  const repaired = view.committedOrderIds.filter(id => target.includes(id)).length
  const restored = repairedOrders(view).reduce((sum, o) => sum + (o.restoredCents ?? 0), 0)
  const complete = target.length > 0 && repaired >= target.length
  const recordedEvidence = recordedProtectedChecks(view)
  const verifiedChecks = recordedEvidence?.checks ?? (live && !generationMismatch ? checks : undefined)
  const guarded = decisionChecks(verifiedChecks)
  const expected = verifiedChecks === undefined ? undefined : guarded.length
  const kept = guarded.filter(isHeld).length
  const violated = guarded.filter(c => c.status === 'violated')
  const stops = view.proposals.filter(p => p.status === 'blocked')
  const layers = Array.from(new Set(stops.flatMap(p => p.blocker ? [p.blocker.layer] : p.decisions.filter(d => d.decisive && !d.shadow && d.outcome === 'block').map(d => d.layer))))
  const beaconCheck = verifiedChecks?.find(c => c.category === 'tenant_isolation')
  const beacon = appState?.beacon
  const beaconUntouched = beaconCheck ? isHeld(beaconCheck) : live && !generationMismatch && !replaying && beacon ? beacon.untouched && beacon.checksum === beacon.expected_checksum : undefined
  const recordLabel = workflow === 'rewindsafe.import_recovery' ? 'Records repaired' : 'Data repaired'
  const checksCaption = violated.length
    ? `Violated: ${violated.map(c => c.label).join('; ')}.`
    : expected === undefined
      ? live ? 'Current data is not run-level verification.' : 'Detailed historical protected checks were not recorded for this run.'
      : expected === 0
        ? 'No protected-check details were recorded for this run.'
        : kept === expected
          ? `VeerIQ: All ${expected} recorded checks preserved at ${recordedEvidence?.source === 'receipt' ? 'commit' : recordedEvidence ? 'run completion' : 'the current check'}.`
          : `${kept} of ${expected} recorded protected checks are preserved.`
  const simulated = isSimulatedEnforcement(enforcement)
  return <section aria-label="Recorded recovery results" className="overflow-hidden rounded-xl border border-line bg-raised">
    <div className="grid grid-cols-2 divide-x divide-line md:grid-cols-4">
      <Promise label={recordLabel} value={grant ? target.length ? <Fraction n={repaired} of={target.length} /> : 'Nothing needed' : <Skeleton className="h-4 w-10" />} fill={target.length ? repaired / target.length : 0} color={complete ? 'var(--outcome-allow)' : 'var(--text-2)'} caption={complete ? `Approved values restored${restored > 0 ? ` · ${formatMoney(restored)}` : ''}.` : target.length ? repaired ? `Some ${workflow === 'rewindsafe.import_recovery' ? 'records' : 'orders'} repaired; the rest left alone.` : live || replaying ? 'Waiting for a committed repair.' : `No ${workflow === 'rewindsafe.import_recovery' ? 'record' : 'order'} repair committed in this run.` : `This task asks for no ${workflow === 'rewindsafe.import_recovery' ? 'record' : 'order'} repairs.`} />
      <Promise label="Today’s decisions kept" value={expected === undefined ? 'Not recorded' : expected ? <Fraction n={kept} of={expected} /> : 'No checks'} fill={expected ? kept / expected : 0} color={violated.length ? 'var(--outcome-block)' : expected && kept === guarded.length && kept > 0 ? 'var(--outcome-allow)' : 'var(--text-2)'} alert={violated.length > 0} caption={checksCaption} />
      <Promise label="Attacks stopped" value={<NumberRoll value={stops.length} />} fill={stops.length ? 1 : 0} color={stops.length ? 'var(--outcome-block)' : 'var(--text-2)'} caption={stops.length ? `Stopped by ${layers.map(l => LAYERS[l].label).join(' and ') || 'a protection layer'}.` : view.proposals.length === 0 ? 'No requests or attack probes were recorded.' : 'No requests were blocked; this run does not show an attack being stopped.'} />
      <Promise label="Other tenant untouched" value={beaconUntouched === undefined ? live ? 'Checking' : 'Not recorded' : beaconUntouched ? <><Check className="size-3.5" aria-hidden />Verified</> : <><ShieldAlert className="size-3.5" aria-hidden />Changed</>} fill={beaconUntouched ? 1 : 0} color={beaconUntouched === undefined ? 'var(--text-2)' : beaconUntouched ? 'var(--outcome-allow)' : 'var(--outcome-block)'} alert={beaconUntouched === false} caption={beaconCheck ? `Recorded at ${recordedEvidence?.source === 'receipt' ? 'commit' : recordedEvidence ? 'run completion' : 'current verification'}.` : live ? 'Waiting for a tenant-isolation check.' : 'No historical tenant-isolation check was recorded.'} />
    </div>
    <Technical><div className="flex flex-wrap gap-x-5 gap-y-2 border-t border-line px-4 py-2.5 text-xs text-ink-2">
      <span>{simulated ? 'Simulated ArmorIQ' : 'Live ArmorIQ'} · {replaying ? 'Recorded event prefix' : live ? 'Updating live' : 'Recorded run'}</span>
      <span>Forbidden effects: {replaying && !view.finish ? 'not reported yet' : metrics?.forbidden_effects_observed ?? 'not reported'}</span>
      <span>Restricted handler entries: {replaying && !view.finish ? 'not reported yet' : metrics?.prohibited_handler_entries ?? 'not reported'}</span>
      {stops.length > 0 && <span>Refused tools: {Array.from(new Set(stops.map(p => toolLabel(p.tool)))).join(', ')}. Blocked requests never ran.</span>}
    </div></Technical>
  </section>
}

export const PromiseStrip = Scoreboard
