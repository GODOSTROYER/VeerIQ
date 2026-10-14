import { useLiveEvidence } from '@/api/hooks'
import type { EnforcementReadiness, GateAEvidence, GateAProbe, InjectionEvalModel, SystemStatus } from '@/api/types'
import { Badge, Disclosure, EmptyState, ErrorState, Skeleton, Tooltip } from '@/components/ui'
import { Technical, useDetail } from '@/lib/detail'
import { DECISION_SOURCES } from '@/lib/layers'
import { formatDate } from '@/lib/format'
const READINESS: Record<EnforcementReadiness['state'], { label: string; color: string }> = {
  verified: { label: 'Connection verified', color: 'var(--outcome-allow)' },
  unverified: { label: 'Connection not yet checked', color: 'var(--outcome-neutral)' },
  failed: { label: 'Last connection check failed', color: 'var(--outcome-unavailable)' },
  simulated: { label: 'Simulated, no live connection', color: 'var(--outcome-hold)' },
}

/** Plain-language names for outcomes the live service reports. */
const OUTCOME_LABEL: Record<string, string> = { allow: 'Allowed', block: 'Blocked', hold: 'Held for approval', unavailable: 'Unavailable', error: 'Error', completed: 'Completed' }
const OUTCOME_COLOR: Record<string, string> = {
  allow: 'var(--outcome-allow)',
  block: 'var(--outcome-block)',
  hold: 'var(--outcome-hold)',
  unavailable: 'var(--outcome-unavailable)',
  error: 'var(--outcome-block)',
}

/** The evidence files are sanitized server-side; strip anything that still looks like an address or token. */
function scrub(text: string): string {
  return text
    .replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, '[email removed]')
    .replace(/token_id=\S+/gi, 'token_id=[removed]')
}

function probeName(p: GateAProbe): string {
  const raw = String(p.probe ?? p.name ?? 'Probe')
  return raw.replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

function sourceLabel(source: string | undefined): string {
  if (!source) return 'Not recorded'
  const meta = (DECISION_SOURCES as Record<string, { label: string }>)[source]
  return meta?.label ?? source
}

/** The recorded file stores its probes as `steps` (name in `step`); accept a `probes` array too. */
function gateAProbes(g: GateAEvidence | null): GateAProbe[] {
  if (!g) return []
  if (Array.isArray(g.probes)) return g.probes
  const steps = (g as { steps?: unknown }).steps
  if (!Array.isArray(steps)) return []
  return steps.map((raw) => {
    const st = (raw ?? {}) as Record<string, unknown>
    const dec = (st.decision ?? {}) as Record<string, unknown>
    return {
      probe: String(st.step ?? 'Probe').replace(/^\d+[a-z]?\s+/, ''),
      outcome: (st.outcome ?? dec.outcome) as string | undefined,
      source: (st.source ?? dec.source) as string | undefined,
      latency_ms: (typeof st.latency_ms === 'number' ? st.latency_ms : (dec.latency_ms as number | null | undefined)) ?? null,
      matched_policy: (st.matched_policy as string | null | undefined) ?? null,
    }
  })
}

function gatePlanHash(g: GateAEvidence | null): string | null {
  if (!g) return null
  if (typeof g.plan_hash === 'string') return g.plan_hash
  const plan = ((g as { findings?: { plan?: { plan_hash?: unknown } } }).findings?.plan) ?? {}
  return typeof plan.plan_hash === 'string' ? plan.plan_hash : null
}

function evidenceDate(g: GateAEvidence | null): string | null {
  const v = g?.created_at ?? g?.date ?? (g as { finished_at?: string } | null)?.finished_at
  return typeof v === 'string' ? v : null
}

function tally(models: InjectionEvalModel[]) {
  return {
    trials: models.reduce((n, m) => n + m.trials, 0),
    attempts: models.reduce((n, m) => n + m.attempted_restore + m.attempted_cross_tenant, 0),
  }
}

function shortModel(model: string): string {
  return model.replace(/^[a-z0-9-]+\//i, '')
}

export function LiveEvidence({ status, region = 'probes' }: { status: SystemStatus | undefined; region?: 'injection' | 'probes' }) {
  const evidence = useLiveEvidence()
  const { technical } = useDetail()
  if (evidence.error && !evidence.data) return <ErrorState compact error={evidence.error} title="Recorded evidence did not load" onRetry={() => void evidence.refetch()} />
  if (!evidence.data) return <div role="status" aria-label="Loading recorded evidence"><Skeleton className={region === 'injection' ? 'h-20 w-full' : 'h-12 w-full'} /></div>
  const { gate_a: gate, gate_a_early: early, injection_eval: inj, readiness } = evidence.data
  if (region === 'injection') {
    if (!inj) return null
    const briefs = inj.briefings?.length ? inj.briefings : [{ briefing: 'task_only', label: 'Task-only briefing', models: inj.models }]
    const top = [...(briefs.find(b => b.briefing === 'task_only')?.models ?? inj.models)].sort((a,b) => b.attempted_restore + b.attempted_cross_tenant - a.attempted_restore - a.attempted_cross_tenant)[0]
    const rules = briefs.find(b => b.briefing === 'with_rules')
    const ruleCount = rules ? tally(rules.models) : null
    return <section aria-label="Injection evaluation" className="space-y-3">
      <p className="max-w-[80ch] text-[15px] leading-relaxed text-ink-2">
        {top ? <>Told only the task, <span className="text-ink">{shortModel(top.model)} followed the planted note in {top.attempted_restore + top.attempted_cross_tenant} of {top.trials} trials</span></> : 'No model trials were recorded'}
        {ruleCount && <>; told the grant’s rules too, models followed it in {ruleCount.attempts} of {ruleCount.trials}</>}{inj.with_enforcement ? ' — every proposed call was refused by ArmorIQ before any handler ran.' : ' — no tools were executed during this evaluation.'}
      </p>
      <Disclosure summary="Compare both briefings and model results">
        <div className="space-y-4">{briefs.map(b => <div key={b.briefing}><h3 className="text-sm font-medium text-ink">{b.label}</h3><ul className="mt-2 space-y-1 text-[13px] text-ink-2">{b.models.map(m => <li key={m.model}>{shortModel(m.model)}: {m.attempted_restore + m.attempted_cross_tenant} of {m.trials} followed it <Technical inline> · {m.attempted_restore} restore-access attempts, {m.attempted_cross_tenant} cross-tenant attempts</Technical></li>)}</ul></div>)}</div>
        <p className="mt-3 text-xs text-ink-3">{inj.created_at ? 'Evaluated ' + formatDate(inj.created_at) + ' against Groq models. ' : ''}Prompt wording changes model behavior; the surrounding boundary enforces the decision.</p>
        <Technical><Disclosure className="mt-3" summary="Raw record"><pre className="max-h-80 overflow-auto rounded-xl bg-sunken p-3 font-mono text-xs text-ink-2">{JSON.stringify(inj, null, 2)}</pre></Disclosure></Technical>
      </Disclosure>
    </section>
  }
  const probes = gateAProbes(gate)
  const date = evidenceDate(gate)
  const ready = readiness ? READINESS[readiness.state] : null
  return <Disclosure summary={<span className="flex flex-wrap items-center gap-3"><span>Recorded live ArmorIQ probes{date ? ' · ' + formatDate(date) : ''}</span>{ready && <Tooltip content={readiness?.detail ?? 'Latest connection probe'}><span><Badge color={ready.color}>{ready.label}</Badge></span></Tooltip>}</span>}>
    <p className="mb-4 text-[13px] text-ink-2">Recorded from the live service; {status ? status.enforcement.simulated ? 'this session is simulated.' : 'this session uses live enforcement.' : 'the current session mode is unavailable.'}</p>
    <Technical><dl className="mb-4 space-y-2 text-xs text-ink-2">{gate?.sdk_version && <div><dt className="inline text-ink-3">ArmorIQ SDK: </dt><dd className="inline">{String(gate.sdk_version)}</dd></div>}{gatePlanHash(gate) && <div><dt className="text-ink-3">Signed plan hash</dt><dd className="break-all font-mono">{gatePlanHash(gate)}</dd></div>}</dl></Technical>
    {probes.length ? <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Recorded live probes"><table className="w-full border-collapse text-left text-[13px]" style={{ minWidth: technical ? 760 : undefined }}>
      <caption className="sr-only">Recorded responses from the live ArmorIQ service</caption>
      <thead><tr className="border-b border-line text-xs text-ink-3"><th className="py-2 pr-3 font-medium">Request</th><th className="py-2 font-medium">Answer</th>{technical && <><th className="px-3 py-2 font-medium">Source</th><th className="px-3 py-2 font-medium">Latency</th><th className="py-2 font-medium">Matched policy</th></>}</tr></thead>
      <tbody className="divide-y divide-line">{probes.map((p,i) => <tr key={i}><th scope="row" className="py-3 pr-3 text-[13px] font-medium text-ink">{probeName(p)}</th><td className="py-3"><Badge color={OUTCOME_COLOR[String(p.outcome)] ?? 'var(--outcome-neutral)'}>{OUTCOME_LABEL[String(p.outcome)] ?? p.outcome ?? 'Not recorded'}</Badge></td>{technical && <><td className="px-3 py-3 text-ink-2">{sourceLabel(p.source)}</td><td className="tabular whitespace-nowrap px-3 py-3 text-ink-2">{typeof p.latency_ms === 'number' ? Math.round(p.latency_ms) + ' ms' : 'n/a'}</td><td className="max-w-xs break-words py-3 text-ink-2">{p.matched_policy ?? 'None'}</td></>}</tr>)}</tbody>
    </table></div> : <EmptyState title="No per-probe results recorded" description="The recorded file has no individual responses. First probe notes may still be available below." />}
    {early && <div className="mt-4"><Disclosure summary="First live probe notes"><p className="text-[13px] leading-relaxed text-ink-2">The original probe notes record the setup and individual observations. Open the raw record in Technical mode to read them in full.</p><Technical><Disclosure className="mt-3" summary="Raw record"><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-sunken p-3 font-mono text-xs text-ink-2">{scrub(early)}</pre></Disclosure></Technical></Disclosure></div>}
  </Disclosure>
}
