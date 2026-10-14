import { useId, useRef, useState } from 'react'
import { ChevronDown, CircleAlert, Info } from 'lucide-react'
import type { SystemStatus } from '@/api/types'
import { useAppState } from '@/api/hooks'
import { useSession } from '@/api/session'
import { normaliseWarnings, plannerLabel, providerLabel } from '@/lib/labels'
import { Technical } from '@/lib/detail'
import { Badge, Button, Digest, SkeletonLines } from '@/components/ui'
import { Popover } from './Popover'
import { ResetDemoButton } from './ResetDemo'

export interface SystemPillProps { status?: SystemStatus; error?: Error; onRetry?: () => void }
export function SystemPill({ status, error, onRetry }: SystemPillProps) {
  const [open, setOpen] = useState(false)
  const anchor = useRef<HTMLButtonElement>(null)
  const id = useId()
  const { identity } = useSession()
  const state = useAppState(open)
  const simulated = status?.enforcement.simulated
  const failed = !!error || status?.enforcement.readiness?.state === 'failed'
  const label = error ? 'Unavailable' : !status ? 'Checking' : simulated ? 'Simulated' : failed ? 'Check failed' : 'Live'
  const color = !status || error ? 'var(--text-3)' : simulated || failed ? 'var(--outcome-hold)' : 'var(--outcome-allow)'
  const e = status?.enforcement
  const p = status?.planner
  return <>
    <button ref={anchor} type="button" aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? id : undefined}
      aria-label={`System · ${label}`} onClick={() => setOpen((v) => !v)}
      className="inline-flex h-9 shrink-0 items-center gap-2 rounded-full border border-line-strong bg-raised px-3 text-[13px] font-medium text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink active:bg-surface-3">
      <span aria-hidden className="size-1.5 rounded-full" style={{ background: color }} />
      <span><span className="hidden sm:inline">System · </span>{label}</span><ChevronDown aria-hidden className="size-3 text-ink-3" />
    </button>
    <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} id={id} label="System status">
      <div className="border-b border-line px-5 py-4">
        <div className="flex items-center justify-between"><h2 className="text-[15px] font-semibold">System</h2><Badge tone={simulated || failed ? 'hold' : status ? 'good' : 'neutral'}>{label}</Badge></div>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-2">ArmorIQ binds tool names. VeerIQ binds arguments.</p>
      </div>
      {!status ? <div className="p-5">{error ? <><p className="text-sm text-ink-2">System status could not be loaded.</p><Button size="sm" className="mt-3" onClick={onRetry}>Check again</Button></> : <SkeletonLines lines={5} />}</div> : <div className="space-y-4 p-5">
        <dl className="space-y-4 text-[13px]">
          <div><dt className="text-ink-3">ArmorIQ</dt><dd className="mt-1 font-medium">{simulated ? 'Local simulation · no ArmorIQ call' : 'Live service'}{e?.sdk_version && <span> · SDK <span className="tabular">{e.sdk_version}</span></span>}</dd>
            <dd className="mt-1 text-ink-2">{e?.readiness ? `Connection: ${e.readiness.state === 'unverified' ? 'not yet verified' : e.readiness.state === 'failed' ? 'check failed' : e.readiness.state}.` : 'Connection has not been probed.'} {e?.readiness?.detail}</dd>
            {!simulated && <dd className="mt-1 text-ink-2">ArmorIQ signs the plan; its SDK refuses off-plan actions locally. In-plan actions are checked by policy on api.armoriq.ai.</dd>}
          </div>
          <div><dt className="text-ink-3">Agent planner</dt><dd className="mt-1 font-medium">{p?.kind === 'llm' ? 'Live language model' : p?.kind === 'harness' ? 'Deterministic boundary harness' : 'Scripted re-enactment'} · {plannerLabel(p!.name, p!.kind)}</dd>
            <dd className="mt-1 text-ink-2">{p?.kind === 'llm' ? 'A real language model plans the steps.' : p?.configured_llm ? `A language model is ready${p.available_providers?.length ? ' (' + p.available_providers.map(providerLabel).join(', ') + ')' : ''}. Choose Live LLM when authorizing a grant; the default is scripted.` : 'No model key is configured. The planner follows a fixed plan; no language model is running.'}</dd>
          </div>
          <div className="grid grid-cols-2 gap-4"><div><dt className="text-ink-3">PostgreSQL</dt><dd className="mt-1" style={{ color: status.database.ok ? 'var(--outcome-allow)' : 'var(--outcome-unavailable)' }}>{status.database.ok ? 'Connected' : 'Unavailable'}</dd></div><div><dt className="text-ink-3">Data generation</dt><dd className="tabular mt-1">{status.fixture_generation}</dd></div></div>
          <div><dt className="text-ink-3">Beacon checksum</dt><dd className="mt-1">{state.data ? (state.data.beacon.untouched ? 'Matches the starting checksum · untouched' : 'Changed from the starting checksum') : state.error ? 'Could not check Beacon data' : 'Checking Beacon data…'}</dd>
            {state.error && <dd className="mt-1"><Button size="sm" variant="ghost" onClick={() => void state.refetch()}>Check Beacon again</Button></dd>}
          </div>
        </dl>
        <Technical><dl className="space-y-3 border-t border-line pt-3 text-xs text-ink-2">
          <div><dt>Current Beacon checksum</dt><dd className="mt-1"><Digest value={state.data?.beacon.checksum} label="Beacon checksum" /></dd></div>
          <div><dt>Expected Beacon checksum</dt><dd className="mt-1"><Digest value={state.data?.beacon.expected_checksum} label="expected Beacon checksum" /></dd></div>
          <div><dt>Planner provider / model</dt><dd className="mt-1 break-all font-mono">{p?.provider ?? 'None'} / {p?.model ?? p?.name}</dd></div>
          <div><dt>Session mode / environment</dt><dd className="mt-1">{e?.session_mode ?? 'None'} / {e?.env ?? 'None'}</dd></div>
          <div><dt>Configured / user email set</dt><dd className="mt-1">{e?.configured ? 'Yes' : 'No'} / {e?.user_email_set ? 'Yes' : 'No'}</dd></div>
          <div><dt>Contract version</dt><dd className="mt-1 font-mono">{status.contract_version}</dd></div>
          {e?.readiness && <div><dt>Probe evidence</dt><dd className="mt-1 break-words">Checked {e.readiness.checked_at ?? 'not yet'} · plan {e.readiness.plan_latency_ms ?? 'n/a'} ms · check {e.readiness.check_latency_ms ?? 'n/a'} ms · policy {e.readiness.matched_policy ?? 'None'}</dd></div>}
        </dl></Technical>
        {normaliseWarnings(status.warnings).length > 0 && <ul className="space-y-2 border-t border-line pt-3">{normaliseWarnings(status.warnings).map((note) => {
          const Icon = note.level === 'info' ? Info : CircleAlert
          return <li key={note.code + note.message} className="flex gap-2 text-xs leading-relaxed text-ink-2"><Icon aria-hidden className="mt-0.5 size-3.5 shrink-0" style={{ color: note.level === 'info' ? 'var(--text-3)' : 'var(--outcome-hold)' }} /><span>{note.message}</span></li>
        })}</ul>}
      </div>}
      {identity?.role === 'operator' && <div className="border-t border-line px-4 py-3"><ResetDemoButton /></div>}
    </Popover>
  </>
}
