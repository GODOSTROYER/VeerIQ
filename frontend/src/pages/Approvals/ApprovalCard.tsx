import { useId, useState } from 'react'
import { Check, Clock3, X } from 'lucide-react'
import type { ApprovalWithPreview, Identity, Run, ScenarioSpec, SnapshotDiffRow } from '@/api/types'
import { Avatar, Badge, Button, Disclosure, HoldToConfirmButton, Money, TimeAgo } from '@/components/ui'
import { formatCountdown } from '@/lib/format'
import { APPROVAL_STATUS } from '@/lib/labels'
import { Technical } from '@/lib/detail'
import { ApprovalDetails } from './ApprovalDetails'
import { manifestOf, personName, repairSummary } from './format'

export type DecideFn = (approval: ApprovalWithPreview, decision: 'approve' | 'reject', note: string) => Promise<void>
export interface ApprovalCardProps {
  approval: ApprovalWithPreview; identity: Identity; identities: Identity[]; runs: Run[] | undefined; scenarios: ScenarioSpec[] | undefined
  orders?: SnapshotDiffRow[]; now: number; onDecide: DecideFn; onSwitchToReviewer?: () => void; reviewerName?: string; defaultOpen?: boolean
}

export function ApprovalCard({ approval: a, identity, identities, runs, scenarios, orders, now, onDecide, onSwitchToReviewer, reviewerName, defaultOpen = false }: ApprovalCardProps) {
  const noteId = useId()
  const titleId = useId()
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const pending = a.status === 'pending'
  const remaining = new Date(a.expires_at).getTime() - now
  const expired = pending && remaining <= 0
  const isRequester = identity.identity_id === a.requested_by
  const canDecide = pending && identity.role === 'reviewer' && !isRequester && !expired
  const requester = identities.find((i) => i.identity_id === a.requested_by)
  const manifest = manifestOf(a)
  const status = APPROVAL_STATUS[a.status]
  const decide = async (decision: 'approve' | 'reject') => {
    if (!canDecide || busy) return
    setBusy(decision); setFailure(null)
    try { await onDecide(a, decision, note.trim()); setNote('') }
    catch (err) { setFailure(err instanceof Error ? err.message : 'The decision did not save. Try again.') }
    finally { setBusy(null) }
  }

  return <article aria-labelledby={titleId} className="rounded-2xl border border-line-strong bg-raised p-5 sm:p-6">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 flex-1 basis-72">
        <h3 id={titleId} className="text-xl font-semibold leading-snug tracking-[-0.025em] text-ink">{repairSummary(a, orders)}</h3>
        <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-ink-2">
          <Avatar name={requester?.name ?? a.requested_by} color={requester?.color} size="sm" />
          <span>{personName(a.requested_by, identities)} asked</span><TimeAgo value={a.requested_at} />
        </p>
      </div>
      <div className="space-y-2 sm:text-right">
        {manifest && <Money cents={manifest.restored_value_cents} className="text-2xl font-semibold tracking-[-0.025em]" />}
        <div><Badge tone={status.tone}>{status.label}</Badge></div>
      </div>
    </div>
    {pending ? <>
      <p className="mt-5 text-sm leading-relaxed text-ink-2"><span className="font-medium text-ink">Why a second person is needed: </span>
        {manifest && manifest.restored_value_cents > 500000 ? 'This repair restores more than $5,000. A second person must approve these exact changes before anything is written.' : 'This repair requires an independent decision before anything is written.'}
      </p>
      <Technical><p className="mt-2 break-words text-xs text-ink-3">Recorded reason: {a.reason}</p></Technical>
      <p className="mt-3 flex items-center gap-1.5 text-xs text-hold"><Clock3 className="size-3.5" aria-hidden />{expired ? 'Request expired · refreshing its status' : `Expires in ${formatCountdown(remaining)}`}</p>
      <div className="mt-5"><Disclosure summary="Review the exact payload" defaultOpen={defaultOpen}>
        <ApprovalDetails approval={a} identities={identities} runs={runs} scenarios={scenarios} />
      </Disclosure></div>
      <div className="mt-5 border-t border-line pt-5">{canDecide ? <div className="space-y-3">
        <label htmlFor={noteId} className="block text-[13px] font-medium text-ink">Note for the record <span className="font-normal text-ink-3">(optional)</span>
          <textarea id={noteId} value={note} onChange={(e) => setNote(e.target.value)} disabled={busy !== null} rows={2} maxLength={500}
            placeholder="Why you approve or reject, for example: matches the invoice export."
            className="mt-2 block w-full resize-y rounded-xl border border-line-strong bg-sunken px-3 py-2 text-sm font-normal text-ink placeholder:text-ink-3 hover:border-focus focus:border-focus focus:outline-none disabled:opacity-50" />
        </label>
        {failure && <p role="alert" className="text-sm text-block">{failure}</p>}
        <div className="flex flex-wrap gap-3">
          <HoldToConfirmButton onConfirm={() => void decide('approve')} icon={<Check />} disabled={busy !== null} loading={busy === 'approve'} className="w-full sm:w-auto">Approve this exact repair</HoldToConfirmButton>
          <HoldToConfirmButton onConfirm={() => void decide('reject')} icon={<X />} disabled={busy !== null} loading={busy === 'reject'} className="approval-reject w-full sm:w-auto !bg-surface-2 !text-block hover:!bg-surface-3 active:!bg-surface">Reject</HoldToConfirmButton>
        </div>
        <p className="text-xs text-ink-3">Hold either button to confirm. Releasing early cancels.</p>
      </div> : <div className="space-y-3">
        <p className="text-sm leading-relaxed text-ink-2">{expired ? 'This request has expired. The agent is told nothing was approved.' : isRequester ? 'You started this run, so someone else has to decide.' : 'Only an approver can decide. You can read everything the approver sees.'}</p>
        {!expired && onSwitchToReviewer && <Button variant="secondary" size="sm" onClick={onSwitchToReviewer}>Switch to {reviewerName ?? 'the approver'} (approver) to decide</Button>}
      </div>}</div>
    </> : <div role="status" className="mt-5 border-t border-line pt-4">
      <p className="flex items-center gap-2 text-sm font-medium" style={{ color: a.status === 'approved' ? 'var(--outcome-allow)' : a.status === 'rejected' ? 'var(--outcome-block)' : 'var(--outcome-neutral)' }}>{a.status === 'approved' ? <Check className="size-4" /> : <X className="size-4" />}{status.label}{a.decided_by && ` by ${personName(a.decided_by, identities)}`} · moving to history</p>
      <p className="mt-2 text-[13px] text-ink-2">{a.status === 'approved' ? 'The database will re-check the data before it commits the repair.' : a.status === 'rejected' ? 'Nothing was written. The agent has been told the repair was not approved.' : 'The request closed without approval. Nothing was approved.'}</p>
    </div>}
  </article>
}
