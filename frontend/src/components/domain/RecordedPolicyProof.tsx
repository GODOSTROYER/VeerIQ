import { sponsorPolicyCheck as check } from '@/data/sponsorPolicyCheck'

const dayFormat = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

/** A dated isolated probe, deliberately separate from the recovery-run timeline. */
export function RecordedPolicyProof() {
  return <section className="border border-line bg-raised p-4 sm:p-5" aria-labelledby="policy-proof-title">
    <h3 id="policy-proof-title" className="text-lg font-semibold tracking-[-0.025em] text-ink">Even a signed plan cannot override policy.</h3>
    <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-2">In a separate check, we included access restoration in a temporary signed plan. ArmorIQ’s server still refused it under the workspace policy. No recovery tool was dispatched.</p>
    <p className="mt-3 text-xs text-ink-3">Recorded policy probe · {dayFormat.format(new Date(check.checked_at))} · Separate from the recovery run</p>
    <details className="mt-3 text-sm"><summary className="w-fit cursor-pointer text-ink underline decoration-line-strong underline-offset-4">Inspect the recorded policy response</summary>
      <dl className="mt-3 grid gap-x-5 gap-y-2 text-xs sm:grid-cols-[120px_minmax(0,1fr)]"><dt className="text-ink-3">Signed plan</dt><dd>Included the prohibited tool</dd><dt className="text-ink-3">Server decision</dt><dd className="text-block">{check.raw_action} · tool_not_in_allowlist</dd><dt className="text-ink-3">Decision source</dt><dd className="break-all font-mono">{check.source}</dd><dt className="text-ink-3">Tool dispatches</dt><dd>{check.local_handler_dispatches}</dd><dt className="text-ink-3">Policy</dt><dd className="break-all font-mono">{check.matched_policy}</dd></dl>
      <a className="mt-3 inline-flex min-h-10 items-center text-xs font-medium text-ink underline underline-offset-4" href="/evidence/sponsor-policy-check.json" download>Download recorded check</a>
    </details>
  </section>
}
