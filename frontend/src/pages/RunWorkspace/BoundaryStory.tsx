import type { RunView } from './model'
import { actionSentence } from './model'
import { sourceLabel } from '@/lib/layers'
import { Button, Disclosure } from '@/components/ui'

/** A recorded cause-and-effect story; only events visible in this replay are used. */
export function BoundaryStory({ view, onInspect }: { view: RunView; onInspect: (id: string) => void }) {
  const attempt = view.proposals.find(p => p.status === 'blocked' && p.blocker)
  if (!attempt) return null
  const note = view.annotations[0]
  const decision = attempt.blocker!
  return <section className="border border-line bg-raised p-4 sm:p-5" aria-labelledby="boundary-story-title">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 id="boundary-story-title" className="text-xl font-semibold tracking-[-0.025em]">The agent tried. The boundary held.</h2><p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-2">A proposed action was refused before its handler ran. The task’s permission did not expand when the agent read the snapshot.</p></div>
      <Button variant="secondary" size="sm" onClick={() => onInspect(attempt.proposalId)}>Inspect blocked action</Button>
    </div>
    <ol className="mt-5 grid gap-5 md:grid-cols-3">
      <li className="min-w-0"><h3 className="text-sm font-medium text-ink">What the agent read</h3>{note ? <Disclosure summary="Read the untrusted snapshot note" className="mt-2"><blockquote className="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink-2">{note.body}</blockquote></Disclosure> : <p className="mt-2 text-sm text-ink-2">No snapshot instruction was recorded for this attempt.</p>}<p className="mt-2 text-xs text-ink-3">Historical content is data. It cannot authorize an action.</p></li>
      <li className="min-w-0"><h3 className="text-sm font-medium text-ink">What it attempted</h3><p className="mt-2 break-words text-sm leading-relaxed" style={{color:'var(--outcome-block)'}}>{actionSentence(attempt.tool,attempt.args,{accessPrincipal:()=>undefined,manifestRows:()=>[]})}</p><p className="mt-2 text-xs text-ink-3">Actual proposal recorded in this run.</p></li>
      <li className="min-w-0"><h3 className="text-sm font-medium text-ink">Why it stopped</h3><p className="mt-2 text-sm leading-relaxed text-ink-2">{decision.source === 'armoriq.sdk.plan_binding' ? 'This action was absent from the signed tool plan. The ArmorIQ SDK refused it locally.' : decision.reason}</p><p className="mt-2 text-xs text-ink-3">{sourceLabel(decision)} · {decision.simulated ? 'Simulated decision' : 'Recorded enforcement decision'}</p></li>
    </ol>
    {view.commits > 0 && <p className="mt-5 border-t border-line pt-4 text-sm text-ink-2">The recovery continued: <span className="font-medium text-ink">{view.committedOrderIds.join(', ') || 'approved records'}</span> repaired in {view.commits} recorded {view.commits === 1 ? 'commit' : 'commits'}. Inspect the recovery record for protected-state checks.</p>}
  </section>
}
