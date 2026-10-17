import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ClipboardCheck, History } from 'lucide-react'
import { motion } from 'motion/react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, errorMessage } from '@/api/client'
import { invalidate, invalidateAppData, TAGS } from '@/api/bus'
import { useQuery, useRuns, useScenarios, useSnapshotDiff } from '@/api/hooks'
import { useSession } from '@/api/session'
import type { ApprovalStatus, ApprovalWithPreview } from '@/api/types'
import { Badge, ErrorState, Loader, Skeleton, useToast } from '@/components/ui'
import { AnimatedItem, AnimatedList } from '@/components/motion'
import { APPROVAL_STATUS } from '@/lib/labels'
import { cn } from '@/lib/cn'
import { T, useMotionOK } from '@/lib/motion'
import { ApprovalCard } from './ApprovalCard'
import { ApprovalHistory } from './ApprovalHistory'
import { SeparationOfDuties } from './SeparationOfDuties'
import { repairSummary } from './format'
import './approvals.css'

export default function Approvals() {
  const { identity, identities, signIn } = useSession()
  const toast = useToast()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const focusId = params.get('focus')
  const motionOK = useMotionOK()
  const [polling, setPolling] = useState(false)
  const approvals = useQuery<ApprovalWithPreview[]>('/approvals', { tags: [TAGS.approvals], refetchInterval: polling ? 2000 : false })
  const runs = useRuns()
  const scenarios = useScenarios()
  const orders = useSnapshotDiff()
  const [now, setNow] = useState(() => Date.now())
  const [moving, setMoving] = useState<Record<string, ApprovalWithPreview>>({})
  const [overrides, setOverrides] = useState<Record<string, ApprovalWithPreview>>({})
  const list = approvals.data
  const effective = useMemo(() => (list ?? []).map((a) => overrides[a.approval_id] ?? a), [list, overrides])
  const pending = useMemo(() => effective.filter((a) => a.status === 'pending').sort((a, b) => a.expires_at.localeCompare(b.expires_at)), [effective])
  const pendingCards = useMemo(() => [...pending.filter((a) => !moving[a.approval_id]), ...Object.values(moving)], [pending, moving])
  const history = useMemo(() => effective.filter((a) => a.status !== 'pending' && !moving[a.approval_id])
    .sort((a, b) => (b.decided_at ?? b.expires_at).localeCompare(a.decided_at ?? a.expires_at)), [effective, moving])

  useEffect(() => setPolling(pending.length > 0), [pending.length])
  useEffect(() => {
    if (!pending.length) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    setNow(Date.now())
    return () => window.clearInterval(id)
  }, [pending.length])
  // Keep the confirmation visible before collapsing the card and inserting its history row.
  useEffect(() => {
    if (!Object.keys(moving).length) return
    const timer = window.setTimeout(() => setMoving({}), 1100)
    return () => window.clearTimeout(timer)
  }, [moving])
  useEffect(() => {
    if (!list) return
    setOverrides((current) => {
      const confirmed = Object.keys(current).filter((id) => list.some((a) => a.approval_id === id && a.status === current[id].status))
      if (!confirmed.length) return current
      const next = { ...current }; confirmed.forEach((id) => delete next[id]); return next
    })
  }, [list])

  const seen = useRef<Map<string, ApprovalStatus> | null>(null)
  const mine = useRef<Set<string>>(new Set())
  useEffect(() => {
    if (!list) return
    const prev = seen.current
    if (prev) for (const a of list) {
      const before = prev.get(a.approval_id)
      if (before === undefined && a.status === 'pending') toast.push({ title: 'New approval request', description: `${repairSummary(a, orders.data)} is waiting for a second person.`, tone: 'hold' })
      else if (before === 'pending' && a.status !== 'pending' && !mine.current.has(a.approval_id)) {
        setMoving((current) => ({ ...current, [a.approval_id]: a }))
        toast.push({ title: `Request ${APPROVAL_STATUS[a.status].label.toLowerCase()}`, description: repairSummary(a, orders.data), tone: a.status === 'approved' ? 'good' : 'neutral' })
      }
    }
    seen.current = new Map(list.map((a) => [a.approval_id, a.status] as const))
  }, [list, toast, orders.data])

  const decide = useCallback(async (approval: ApprovalWithPreview, decision: 'approve' | 'reject', note: string) => {
    mine.current.add(approval.approval_id)
    try {
      const result = await api.post<ApprovalWithPreview>(`/approvals/${approval.approval_id}/decide`, { decision, ...(note ? { note } : {}) })
      const resolved = { ...approval, ...result }
      setOverrides((current) => ({ ...current, [approval.approval_id]: resolved }))
      setMoving((current) => ({ ...current, [approval.approval_id]: resolved }))
      invalidate(TAGS.approvals, TAGS.runs, TAGS.run(approval.run_id)); invalidateAppData()
      toast.push({ title: decision === 'approve' ? 'Approved' : 'Rejected',
        description: decision === 'approve' ? 'The database will re-check the data before it commits the repair.' : 'Nothing was written. The agent has been told the repair was not approved.',
        tone: decision === 'approve' ? 'good' : 'neutral', action: { label: 'Back to the run', onClick: () => navigate(`/runs/${approval.run_id}`) } })
    } catch (err) {
      mine.current.delete(approval.approval_id)
      toast.error(decision === 'approve' ? 'Could not approve' : 'Could not reject', errorMessage(err))
      invalidate(TAGS.approvals)
      throw err
    }
  }, [toast, navigate])

  const focusedRef = useRef<string | null>(null)
  useEffect(() => {
    if (!focusId) { focusedRef.current = null; return }
    if (!list || focusedRef.current === focusId) return
    const el = document.getElementById(`approval-${focusId}`)
    if (!el) return
    focusedRef.current = focusId
    const frame = requestAnimationFrame(() => el.scrollIntoView({ behavior: motionOK ? 'smooth' : 'auto', block: 'center' }))
    return () => cancelAnimationFrame(frame)
  }, [focusId, list, moving, motionOK])

  if (!identity) return null
  const reviewer = identities.find((i) => i.role === 'reviewer' && i.tenant_id === identity.tenant_id && i.identity_id !== identity.identity_id)
  const switchToReviewer = reviewer ? async () => {
    try { await signIn(reviewer.identity_id) }
    catch (err) { toast.error('Could not switch to the approver', errorMessage(err)) }
  } : undefined

  return <div className="space-y-8">
    <header className="max-w-3xl">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-[32px] font-semibold leading-tight tracking-[-0.03em] text-ink">Approvals</h1>
        {list && <Badge tone={pending.length ? 'hold' : 'neutral'}>{pending.length ? `${pending.length} waiting for a decision` : 'Nothing waiting'}</Badge>}
      </div>
      <p className="mt-2 max-w-[68ch] text-[15px] leading-relaxed text-ink-2">High-value repairs pause here. A second person reviews the exact changes before the agent can write them.</p>
      <p className="mt-1 text-xs text-ink-3">Open requests refresh automatically.</p>
    </header>
    <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_272px]">
      <div className="min-w-0 space-y-8">
        {approvals.error && <div><ErrorState error={approvals.error} title={list ? 'Approvals could not refresh' : 'Approvals did not load'} onRetry={() => void approvals.refetch()} />
          <p className="text-center text-[13px] text-ink-2">{list ? 'The record below may be out of date. Retry to check the latest requests.' : 'Retry to load the requests and their decision history.'}</p>
        </div>}
        {!list && !approvals.error ? <ApprovalsSkeleton /> : list && <>
          <motion.section layout={motionOK} transition={T.layout} aria-labelledby="pending-title" className="space-y-4">
            <h2 id="pending-title" className="text-lg font-semibold tracking-[-0.02em] text-ink">Waiting for a decision</h2>
            {pendingCards.length === 0 ? <div className="flex flex-col items-start gap-4 rounded-2xl border border-line bg-raised p-5 sm:flex-row sm:p-6">
              <ClipboardCheck className="mt-1 size-5 shrink-0 text-ink-3" aria-hidden />
              <div><h3 className="text-base font-medium text-ink">No repairs are waiting</h3>
                <p className="mt-2 max-w-[56ch] text-sm leading-relaxed text-ink-2">Start the high-value scenario from Workspace; it pauses here for a second person to review the repair before anything is written.</p>
                <Link to="/workspace" className="mt-4 inline-flex min-h-10 items-center rounded-lg border border-line-strong px-3 text-[13px] font-medium text-ink transition-colors hover:bg-surface-2 active:bg-surface-3">Go to Workspace</Link>
              </div>
            </div> : <AnimatedList as="ul" className="space-y-4">{pendingCards.map((a) => <AnimatedItem key={a.approval_id} id={`approval-${a.approval_id}`} className={cn('scroll-mt-44 rounded-2xl', focusId === a.approval_id && 'outline outline-2 -outline-offset-2 outline-focus')}>
              <ApprovalCard approval={a} identity={identity} identities={identities} runs={runs.data} scenarios={scenarios.data} orders={orders.data} now={now} onDecide={decide} onSwitchToReviewer={switchToReviewer} reviewerName={reviewer?.name} />
            </AnimatedItem>)}</AnimatedList>}
          </motion.section>
          <motion.section layout={motionOK} transition={T.layout} aria-labelledby="history-title" className="space-y-4">
            <h2 id="history-title" className="flex items-center gap-2 text-lg font-semibold tracking-[-0.02em] text-ink"><History className="size-4 text-ink-3" aria-hidden />Decided history</h2>
            {history.length ? <ApprovalHistory approvals={history} identities={identities} runs={runs.data} scenarios={scenarios.data} orders={orders.data} focusId={focusId} /> : <p className="rounded-2xl border border-dashed border-line-strong px-5 py-6 text-[13px] leading-relaxed text-ink-2">Approved, rejected and expired requests collect here with the approver, timestamps and note. Expand a row to see exactly what was reviewed.</p>}
          </motion.section>
        </>}
      </div>
      <SeparationOfDuties />
    </div>
  </div>
}

function ApprovalsSkeleton() {
  return <div className="space-y-8" role="status" aria-label="Loading approvals">
    <div className="flex items-center gap-2 text-sm text-ink-2"><Loader size="sm" label="Loading approval requests" />Loading requests and decisions</div>
    <div className="space-y-4"><Skeleton className="h-6 w-48" /><div className="space-y-4 rounded-2xl border border-line bg-raised p-6"><Skeleton className="h-7 w-4/5" /><Skeleton className="h-4 w-1/2" /><Skeleton className="h-12 w-full" /><Skeleton className="h-11 w-full" /><Skeleton className="h-16 w-full" /><div className="flex gap-3"><Skeleton className="h-12 w-3/5" /><Skeleton className="h-12 w-1/3" /></div></div></div>
    <div className="space-y-4"><Skeleton className="h-6 w-40" /><div className="divide-y divide-line rounded-2xl border border-line bg-raised px-4">{Array.from({ length: 5 }, (_, i) => <div key={i} className="grid grid-cols-[2fr_1fr_1fr] gap-4 py-4"><Skeleton className="h-4" /><Skeleton className="h-4" /><Skeleton className="h-4" /></div>)}</div></div>
  </div>
}
