import { Fragment, useId, useState } from 'react'
import { motion } from 'motion/react'
import { ChevronDown } from 'lucide-react'
import type { ApprovalWithPreview, Identity, Run, ScenarioSpec, SnapshotDiffRow } from '@/api/types'
import { Badge, Button, Money, TimeAgo } from '@/components/ui'
import { Collapse } from '@/components/motion'
import { APPROVAL_STATUS } from '@/lib/labels'
import { cn } from '@/lib/cn'
import { T, useMotionOK } from '@/lib/motion'
import { Technical } from '@/lib/detail'
import { ApprovalDetails } from './ApprovalDetails'
import { personName, repairSummary } from './format'

export function ApprovalHistory({ approvals, identities, runs, scenarios, orders, focusId }: {
  approvals: ApprovalWithPreview[]; identities: Identity[]; runs?: Run[]; scenarios?: ScenarioSpec[]; orders?: SnapshotDiffRow[]; focusId: string | null
}) {
  const [showAll, setShowAll] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [closedFocus, setClosedFocus] = useState<string | null>(null)
  const prefix = useId()
  const motionOK = useMotionOK()
  const focusOutside = approvals.findIndex((a) => a.approval_id === focusId) >= 5
  const allVisible = showAll || focusOutside
  const visible = allVisible ? approvals : approvals.slice(0, 5)
  return <div className="overflow-hidden rounded-2xl border border-line bg-raised">
    <table className="approval-history w-full table-fixed text-left text-[13px]">
      <caption className="sr-only">Decided requests. Expand a repair to review its exact payload and decision record.</caption>
      <colgroup><col className="w-[35%]" /><col className="w-[15%]" /><col className="w-[15%]" /><col className="w-[13%]" /><col className="w-[22%]" /></colgroup>
      <thead className="text-xs text-ink-3"><tr>{['Repair', 'Amount', 'Decision', 'By whom', 'When'].map((label) => <th scope="col" key={label} className="px-4 py-3 font-medium">{label}</th>)}</tr></thead>
      <tbody>{visible.map((a) => {
        const open = expanded.has(a.approval_id) || (focusId === a.approval_id && closedFocus !== focusId)
        const status = APPROVAL_STATUS[a.status]
        const bodyId = `${prefix}-${a.approval_id}`
        const toggle = () => {
          if (focusId === a.approval_id) setClosedFocus(open ? focusId : null)
          setExpanded((current) => { const next = new Set(current); if (open) next.delete(a.approval_id); else next.add(a.approval_id); return next })
        }
        return <Fragment key={a.approval_id}>
          <motion.tr id={`approval-${a.approval_id}`} layout={motionOK} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ ...T.base, layout: T.layout }}
            className={cn('approval-history-row scroll-mt-44 border-t border-line', open && 'bg-surface', focusId === a.approval_id && 'bg-surface-2 outline outline-2 -outline-offset-2 outline-focus')}>
            <th scope="row" className="px-4 py-3 font-medium">
              <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={toggle} className="-m-1 flex w-[calc(100%+8px)] items-start gap-2 rounded-lg p-1 text-left text-ink transition-colors hover:bg-surface-2 active:bg-surface-3">
                <ChevronDown className={cn('mt-0.5 size-3.5 shrink-0 transition-transform motion-reduce:transition-none', open && 'rotate-180')} aria-hidden />
                <span>{repairSummary(a, orders, false)}<Technical><span className="mt-1 block break-all font-mono text-[11px] font-normal text-ink-3">{a.approval_id}</span></Technical></span>
              </button>
            </th>
            <td data-label="Amount" className="px-4 py-3 text-ink">{a.manifest ? <Money cents={a.manifest.restored_value_cents} /> : <span className="text-ink-3">Not recorded</span>}</td>
            <td data-label="Decision" className="px-4 py-3"><Badge tone={status.tone}>{status.label}</Badge></td>
            <td data-label="By whom" className="px-4 py-3 text-ink-2">{personName(a.decided_by, identities)}</td>
            <td data-label="When" className="px-4 py-3 text-ink-2"><TimeAgo value={a.decided_at ?? a.expires_at} /></td>
          </motion.tr>
          <tr className="approval-history-detail"><td colSpan={5} className="p-0"><Collapse open={open} id={bodyId}><div className="border-t border-line bg-sunken p-4 sm:p-5"><ApprovalDetails approval={a} identities={identities} runs={runs} scenarios={scenarios} /></div></Collapse></td></tr>
        </Fragment>
      })}</tbody>
    </table>
    {approvals.length > 5 && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3">
      <p className="text-xs text-ink-3">{allVisible ? `All ${approvals.length} requests` : `Latest 5 of ${approvals.length} requests`}</p>
      <Button variant="ghost" size="sm" disabled={focusOutside} onClick={() => setShowAll((v) => !v)}>{allVisible ? 'Show latest 5' : 'Show all'}</Button>
    </div>}
  </div>
}
