import { Link } from 'react-router-dom'
import { ExternalLink, FlaskConical, ShieldCheck } from 'lucide-react'
import type { ApprovalWithPreview, Identity, Run, ScenarioSpec } from '@/api/types'
import { Badge, Digest } from '@/components/ui'
import { Technical } from '@/lib/detail'
import { formatDateTime } from '@/lib/format'
import { tenantName, toolLabel } from '@/lib/labels'
import { describeConstraints, fieldText, formatChangeValue, manifestOf, personName } from './format'

export function ApprovalDetails({ approval: a, identities, runs, scenarios }: {
  approval: ApprovalWithPreview; identities: Identity[]; runs?: Run[]; scenarios?: ScenarioSpec[]
}) {
  const manifest = manifestOf(a)
  const requester = identities.find((i) => i.identity_id === a.requested_by)
  const run = runs?.find((r) => r.run_id === a.run_id)
  const scenario = scenarios?.find((s) => s.scenario_id === run?.scenario_id)
  const constraints = describeConstraints(a.state_constraints)
  const simulated = a.sponsor_status === 'simulated'
  const noHold = !a.sponsor_delegation_id && !a.sponsor_status
  const sponsorMessages: Record<string, string> = { pending: 'Waiting for the delegation to be approved', approved: 'Delegation approved', rejected: 'Delegation rejected', timeout: 'Delegation timed out' }
  const sponsorDetail = simulated ? 'A local simulation of an ArmorIQ hold. It is not a decision from the live service.'
    : noHold ? 'This review comes from VeerIQ rules alone.'
    : a.sponsor_status ? (sponsorMessages[a.sponsor_status] ?? a.sponsor_status) : 'Delegation issued'

  return <div className="space-y-5 text-[13px] leading-relaxed">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-ink-2">{personName(a.requested_by, identities)} asked on {formatDateTime(a.requested_at)}.</p>
      <Link to={`/runs/${a.run_id}`} className="inline-flex items-center gap-1 rounded text-ink-2 underline decoration-line-strong underline-offset-4 hover:text-ink active:text-white">
        {scenario?.title ?? 'Open recovery run'} <ExternalLink className="size-3" aria-hidden />
      </Link>
    </div>
    {a.status !== 'pending' && <div>
      <p className="text-ink-2">{a.decided_by ? `Decision by ${personName(a.decided_by, identities)} on ${formatDateTime(a.decided_at)}.` : `Closed on ${formatDateTime(a.decided_at ?? a.expires_at)} with no reviewer decision.`}</p>
      <p className="mt-1 whitespace-pre-wrap break-words text-ink"><span className="text-ink-3">Note: </span>{a.note || 'No note was recorded.'}</p>
      <p className="mt-2 text-ink-2"><span className="font-medium text-ink">Why a second person was asked: </span>{a.reason}</p>
    </div>}
    <div>
      <h4 className="mb-2 font-semibold text-ink">{a.status === 'pending' ? 'Changes that will be written' : 'Changes submitted for review'}</h4>
      {manifest ? <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full min-w-[520px] text-left">
          <caption className="sr-only">Exact payload for this repair</caption>
          <thead className="border-b border-line bg-sunken text-xs text-ink-3"><tr>
            {['Order', 'Field', 'Today', 'After repair', 'Value comes from'].map((label) => <th key={label} scope="col" className="px-3 py-2 font-medium">{label}</th>)}
          </tr></thead>
          <tbody className="divide-y divide-line">{manifest.changes.map((c) => <tr key={`${c.entity}:${c.row_id}:${c.field}`}>
            <th scope="row" className="px-3 py-2 font-medium">{c.row_id}</th>
            <td className="px-3 py-2 text-ink-2">{fieldText(c.field)}<Technical inline><span className="ml-1 font-mono text-xs">({c.op})</span></Technical></td>
            <td className="tabular px-3 py-2 text-block">{formatChangeValue(c.field, c.current_value)}</td>
            <td className="tabular px-3 py-2 font-medium text-allow">{formatChangeValue(c.field, c.new_value)}</td>
            <td className="px-3 py-2 text-xs text-ink-3">Approved snapshot<Technical><span className="break-all font-mono">{c.source_path}</span></Technical></td>
          </tr>)}</tbody>
        </table>
      </div> : <p className="text-ink-2">The change list is not available for this request. The decision approves only the payload identified by the digest below.</p>}
      {manifest && <p className="mt-2 text-xs text-ink-3">Every new value is read from the approved snapshot by VeerIQ code. The agent cannot supply values.</p>}
    </div>
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
      <div className="min-w-0 sm:col-span-2"><dt className="text-xs text-ink-3">Payload digest you are approving</dt><dd className="mt-1"><Digest value={a.payload_digest} head={14} tail={8} label="payload digest" /></dd></div>
      <div><dt className="text-xs text-ink-3">Targets</dt><dd className="mt-1 break-words text-ink">{a.targets.join(', ') || '—'}</dd></div>
      <div><dt className="text-xs text-ink-3">Tenant</dt><dd className="mt-1 text-ink">{tenantName(requester?.tenant_id ?? manifest?.tenant_id ?? '')}</dd></div>
      <div className="min-w-0 sm:col-span-2"><dt className="text-xs text-ink-3">ArmorIQ</dt><dd className="mt-1 space-y-2">
        <Badge tone={simulated ? 'hold' : 'neutral'} dashed={simulated} icon={simulated ? <FlaskConical /> : <ShieldCheck />}>{simulated ? 'Simulated hold' : noHold ? 'No ArmorIQ hold' : 'ArmorIQ hold'}</Badge>
        <p className="text-ink-2">{sponsorDetail}</p>
        <p className="text-xs text-ink-3">ArmorIQ binds tool names; VeerIQ binds arguments.</p>
      </dd></div>
    </dl>
    <div>
      <h4 className="font-semibold text-ink">State this approval depends on</h4>
      {constraints.length ? <ul className="mt-2 space-y-1.5">{constraints.map((c) => <li key={`${c.label}:${c.value}`} className="break-words text-ink-2"><span className="font-medium text-ink">{c.label}. </span>{c.value}</li>)}</ul> : <p className="mt-1 text-ink-2">No extra state constraints were recorded.</p>}
      <p className="mt-2 text-xs text-ink-3">If any of this changes before the commit, the repair is rejected and nothing is written.</p>
    </div>
    <dl className="grid gap-3 border-t border-line pt-3 text-xs text-ink-2 sm:grid-cols-2">
      <div><dt className="text-ink-3">Requested</dt><dd>{formatDateTime(a.requested_at)}</dd></div>
      <div><dt className="text-ink-3">Expires</dt><dd>{formatDateTime(a.expires_at)}</dd></div>
      {a.decided_at && <div><dt className="text-ink-3">Decided</dt><dd>{formatDateTime(a.decided_at)}</dd></div>}
    </dl>
    <Technical><div className="space-y-3 border-t border-line pt-3">
      <h4 className="font-semibold text-ink">Technical record</h4>
      <dl className="grid gap-3 sm:grid-cols-2">{Object.entries({
        'Approval id': a.approval_id, 'Run id': a.run_id, 'Grant id': a.grant_id, 'Proposal id': a.proposal_id,
        Tool: `${toolLabel(a.tool)} (${a.tool})`, 'Manifest id': a.manifest_id, 'Delegation id': a.sponsor_delegation_id,
        'Sponsor status': a.sponsor_status, 'Snapshot id': manifest?.snapshot_id,
      }).map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-xs text-ink-3">{label}</dt><dd className="mt-1 break-all font-mono text-xs text-ink-2">{value ?? '—'}</dd></div>)}</dl>
      {manifest && <div><p className="text-xs text-ink-3">Snapshot digest</p><Digest value={manifest.snapshot_digest} label="snapshot digest" /></div>}
      <pre className="max-h-80 overflow-auto rounded-xl bg-sunken p-3 font-mono text-xs text-ink-2" aria-label="Raw approval state constraints">{JSON.stringify(a.state_constraints, null, 2)}</pre>
      {manifest && <pre className="max-h-80 overflow-auto rounded-xl bg-sunken p-3 font-mono text-xs text-ink-2" aria-label="Complete execution manifest">{JSON.stringify(manifest, null, 2)}</pre>}
    </div></Technical>
  </div>
}
