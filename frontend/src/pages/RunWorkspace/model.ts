import type {
  ActionProposal,
  ApprovalRecord,
  Decision,
  ExecutionManifest,
  ExecutionReceipt,
  PlanBinding,
  ProposalSource,
  ProposalStatus,
  Run,
  RunEvent,
  RunStatus,
} from '@/api/types'
import { EMPTY_TEXT, formatMoney, titleCase } from '@/lib/format'
import { fieldLabel, tenantName, toolLabel } from '@/lib/labels'
import { sourceLabel } from '@/lib/layers'

/* ─── Defensive readers for event payloads (the contract types `data` loosely) ─── */

export function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
}
export function str(v: unknown): string | undefined {
  return typeof v === 'string' && v.length > 0 ? v : undefined
}
export function num(v: unknown): number | undefined {
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined
}
export function strList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
}

export function joinList(items: string[], max = 3): string {
  if (items.length === 0) return ''
  if (items.length === 1) return items[0]
  if (items.length > max) return `${items.slice(0, max).join(', ')} and ${items.length - max} more`
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

export function times(n: number): string {
  return n === 1 ? 'once' : n === 2 ? 'twice' : `${n} times`
}

/** A null or empty value. Render it in the muted text colour, never as a raw word. */
export function isEmptyValue(v: unknown): boolean {
  return v === null || v === undefined || v === ''
}

export function formatFieldValue(field: string, v: unknown): string {
  if (isEmptyValue(v)) return EMPTY_TEXT
  if (field === 'total_cents' && typeof v === 'number') return formatMoney(v)
  if (typeof v === 'string') return field === 'status' ? titleCase(v) : v
  return String(v)
}

/**
 * The backend fills a missing piece of a sentence with a placeholder, e.g. "for incident n/a on tenant atlas".
 * This drops that clause, so the sentence reads on without it.
 */
const ABSENT_CLAUSE = /\s+(?:for incident|for tenant|on tenant|for grant|for run)\s+(?:n\/a|none|null|undefined)(?=[\s.,;:)]|$)/gi

export function scrubPlaceholders(text: string): string {
  return text.replace(ABSENT_CLAUSE, '')
}

/* ─── Run titles ─── */

export const IMPORT_WORKFLOW = 'rewindsafe.import_recovery'

/** Import runs use an internal dataset id (imp_...) as their scenario id. */
export function isImportRun(run: Pick<Run, 'workflow' | 'scenario_id'>): boolean {
  return run.workflow === IMPORT_WORKFLOW || run.scenario_id.startsWith('imp_')
}

export interface RunHeading {
  title: string
  /** The internal id, shown as secondary monospace text under the title. */
  rawId: string | undefined
}

/**
 * The page title for a run. Prefers the listed scenario title (for imports, that is the dataset's own name).
 * Otherwise import runs read "Imported dataset recovery", never a title-cased internal id.
 */
export function runHeading(run: Pick<Run, 'workflow' | 'scenario_id'>, listedTitle: string | undefined): RunHeading {
  const importRun = isImportRun(run)
  if (listedTitle) return { title: listedTitle, rawId: importRun ? run.scenario_id : undefined }
  if (importRun) return { title: 'Imported dataset recovery', rawId: run.scenario_id }
  return { title: titleCase(run.scenario_id), rawId: undefined }
}

/* ─── Timeline model ─── */

interface ItemBase {
  key: string
  seq: number
  ts: string
}

export interface ProposalItem extends ItemBase {
  kind: 'proposal'
  proposalId: string
  tool: string
  args: Record<string, unknown>
  rationale: string
  source: ProposalSource | undefined
  stepIndex: number | undefined
  decisions: Decision[]
  resultSummary: string | undefined
  status: ProposalStatus
  /** First non-shadow blocking decision (the layer that stopped it), preferring the decisive one. */
  blocker: Decision | undefined
  unavailable: Decision | undefined
}

export interface ManifestItem extends ItemBase {
  kind: 'manifest'
  manifest: ExecutionManifest
  status: ExecutionManifest['status']
}
export interface ApprovalItem extends ItemBase {
  kind: 'approval'
  approval: ApprovalRecord
  resolved: boolean
}
export interface CommitItem extends ItemBase {
  kind: 'commit'
  receipt: ExecutionReceipt
}
export interface Annotation {
  annotationId: string
  author: string
  createdAt: string | undefined
  body: string
  trust: string
}

/** Reads annotations from an event payload or app state, tolerating missing fields. */
export function parseAnnotations(v: unknown): Annotation[] {
  if (!Array.isArray(v)) return []
  const out: Annotation[] = []
  for (const raw of v) {
    const a = rec(raw)
    const body = str(a.body)
    if (!body) continue
    out.push({
      annotationId: str(a.annotation_id) ?? `ANN-${out.length + 1}`,
      author: str(a.author) ?? 'unknown author',
      createdAt: str(a.created_at),
      body,
      trust: str(a.trust) ?? 'untrusted',
    })
  }
  return out
}

export type TimelineItem =
  | ProposalItem
  | ManifestItem
  | ApprovalItem
  | CommitItem
  | (ItemBase & { kind: 'plan'; plan: PlanBinding | undefined; event: RunEvent; latencyMs: number | undefined; matchedPolicies: string[] })
  | (ItemBase & { kind: 'planRequest'; event: RunEvent })
  | (ItemBase & { kind: 'untrusted'; annotations: Annotation[]; toolProposalId: string | undefined })
  | (ItemBase & { kind: 'planFailed'; event: RunEvent })
  | (ItemBase & { kind: 'note'; event: RunEvent })
  | (ItemBase & { kind: 'supervisor'; event: RunEvent })
  | (ItemBase & { kind: 'decision'; decision: Decision })
  | (ItemBase & { kind: 'rejected'; event: RunEvent })
  | (ItemBase & { kind: 'duplicate'; event: RunEvent })
  | (ItemBase & { kind: 'replan'; event: RunEvent })
  | (ItemBase & { kind: 'external'; event: RunEvent })
  | (ItemBase & { kind: 'finish'; event: RunEvent })

export interface RunView {
  items: TimelineItem[]
  proposals: ProposalItem[]
  decisions: Array<{ decision: Decision; tool: string | undefined }>
  manifests: ExecutionManifest[]
  receipts: ExecutionReceipt[]
  approvals: ApprovalRecord[]
  rejections: RunEvent[]
  externals: RunEvent[]
  steps: number
  replans: number
  commits: number
  blockedProposals: number
  status: RunStatus | undefined
  plan: PlanBinding | undefined
  finish: RunEvent | undefined
  committedOrderIds: string[]
  /** Untrusted notes the agent saw, in the order they appeared. */
  annotations: Annotation[]
  /** When ArmorIQ was asked to sign the plan (plan.requested), if that event was seen. */
  planRequestedAt: string | undefined
  planLatencyMs: number | undefined
  matchedPolicies: string[]
}

export interface BuildOptions {
  /** Used when the inspect_snapshot result carries no annotations itself (app state has them). */
  fallbackAnnotations?: Annotation[]
}

interface Facts {
  committed: boolean
  rejectedExec: boolean
  duplicate: boolean
  toolResult: boolean
  approval: ApprovalRecord | undefined
}

function proposalStatus(p: ProposalItem, f: Facts | undefined, fallback: ProposalStatus | undefined): ProposalStatus {
  if (p.blocker) return 'blocked'
  if (p.unavailable) return 'unavailable'
  if (f?.committed) return 'executed'
  if (f?.duplicate) return 'duplicate'
  if (f?.rejectedExec) return 'stale'
  if (f?.approval) {
    const s = f.approval.status
    if (s === 'pending') return 'held'
    if (s === 'rejected' || s === 'timed_out' || s === 'expired' || s === 'cancelled') return 'rejected'
  }
  if (f?.toolResult) return 'executed'
  return fallback && fallback !== 'pending' ? fallback : 'pending'
}

/**
 * Folds the event stream into what the timeline shows. It is a pure function of the events it is given,
 * so a replay (a prefix of the events) renders exactly what a live viewer saw at that moment.
 */
export function buildRunView(
  events: readonly RunEvent[],
  detailProposals?: ReadonlyMap<string, ActionProposal>,
  useDetailFallback = false,
  options: BuildOptions = {},
): RunView {
  const items: TimelineItem[] = []
  const proposals: ProposalItem[] = []
  const byProposal = new Map<string, ProposalItem>()
  const approvalItems = new Map<string, ApprovalItem>()
  const manifestItems: ManifestItem[] = []
  const facts = new Map<string, Facts>()
  const decisions: RunView['decisions'] = []
  const manifests: ExecutionManifest[] = []
  const receipts: ExecutionReceipt[] = []
  const rejections: RunEvent[] = []
  const externals: RunEvent[] = []
  const rejectedManifestIds = new Set<string>()
  const committedManifestIds = new Set<string>()
  let replans = 0
  let steps = 0
  let status: RunStatus | undefined
  let plan: PlanBinding | undefined
  let finish: RunEvent | undefined
  let planRequestedAt: string | undefined
  let planLatencyMs: number | undefined
  let matchedPolicies: string[] = []
  const annotations: Annotation[] = []
  const seenAnnotations = new Set<string>()
  let requestIdx = -1

  const fact = (pid: string | null | undefined): Facts | undefined => {
    if (!pid) return undefined
    let f = facts.get(pid)
    if (!f) {
      f = { committed: false, rejectedExec: false, duplicate: false, toolResult: false, approval: undefined }
      facts.set(pid, f)
    }
    return f
  }

  for (const e of events) {
    const d = rec(e.data)
    const base = { key: `e${e.seq}`, seq: e.seq, ts: e.ts }
    switch (e.type) {
      case 'run.status': {
        const s = str(d.status)
        if (s) status = s as RunStatus
        break
      }
      case 'plan.requested': {
        planRequestedAt = e.ts
        if (requestIdx < 0 && !plan) {
          requestIdx = items.length
          items.push({ ...base, kind: 'planRequest', event: e })
        }
        break
      }
      case 'plan.bound': {
        const bound = d.plan ? (d.plan as PlanBinding) : undefined
        plan = bound ?? plan
        planLatencyMs = num(d.latency_ms) ?? planLatencyMs
        const fromEvent = strList(d.matched_policies)
        const fromPlan = strList(rec(bound).matched_policies)
        matchedPolicies = fromEvent.length ? fromEvent : fromPlan.length ? fromPlan : matchedPolicies
        const next: TimelineItem = { ...base, kind: 'plan', plan: bound, event: e, latencyMs: planLatencyMs, matchedPolicies }
        if (requestIdx >= 0) {
          // The signing card becomes the plan card in place, so the timeline does not jump.
          items[requestIdx] = { ...next, key: items[requestIdx].key, seq: items[requestIdx].seq, ts: items[requestIdx].ts }
          requestIdx = -1
        } else {
          items.push(next)
        }
        break
      }
      case 'plan.bind_failed': {
        const failed: TimelineItem = { ...base, kind: 'planFailed', event: e }
        if (requestIdx >= 0) {
          items[requestIdx] = { ...failed, key: items[requestIdx].key, seq: items[requestIdx].seq, ts: items[requestIdx].ts }
          requestIdx = -1
        } else {
          items.push(failed)
        }
        break
      }
      case 'agent.note':
        items.push({ ...base, kind: e.actor === 'system' && (d.kind === 'supervisor_check' || e.title.startsWith('Automatic supervisor check:')) ? 'supervisor' : 'note', event: e })
        break
      case 'agent.proposal': {
        const pid = e.proposal_id ?? str(d.proposal_id) ?? `seq-${e.seq}`
        const known = detailProposals?.get(pid)
        const item: ProposalItem = {
          ...base,
          key: `p${pid}`,
          kind: 'proposal',
          proposalId: pid,
          tool: str(d.tool) ?? known?.tool ?? 'unknown',
          args: rec(d.arguments ?? known?.arguments),
          rationale: str(d.rationale) ?? known?.rationale ?? '',
          source: (str(d.source) as ProposalSource | undefined) ?? known?.source,
          stepIndex: num(d.step_index) ?? known?.step_index,
          decisions: [],
          resultSummary: undefined,
          status: 'pending',
          blocker: undefined,
          unavailable: undefined,
        }
        items.push(item)
        proposals.push(item)
        byProposal.set(pid, item)
        steps += 1
        break
      }
      case 'decision': {
        if (!e.decision) break
        const target = e.proposal_id ? byProposal.get(e.proposal_id) : undefined
        decisions.push({ decision: e.decision, tool: target?.tool })
        if (target) {
          if (!target.decisions.some((x) => x.decision_id === e.decision!.decision_id)) target.decisions.push(e.decision)
        } else {
          items.push({ ...base, kind: 'decision', decision: e.decision })
        }
        break
      }
      case 'tool.result': {
        const target = e.proposal_id ? byProposal.get(e.proposal_id) : undefined
        if (target) target.resultSummary = str(d.summary) ?? str(e.detail)
        const f = fact(e.proposal_id)
        if (f) f.toolResult = true
        let seen = parseAnnotations(d.annotations)
        if (seen.length === 0 && target?.tool === 'inspect_snapshot') seen = options.fallbackAnnotations ?? []
        const fresh = seen.filter((a) => !seenAnnotations.has(a.annotationId))
        if (fresh.length > 0) {
          fresh.forEach((a) => seenAnnotations.add(a.annotationId))
          annotations.push(...fresh)
          items.push({ ...base, key: `n${e.seq}`, kind: 'untrusted', annotations: fresh, toolProposalId: e.proposal_id ?? undefined })
        }
        break
      }
      case 'manifest.prepared': {
        const manifest = d.manifest as ExecutionManifest | undefined
        if (!manifest) break
        manifests.push(manifest)
        const item: ManifestItem = { ...base, kind: 'manifest', manifest, status: manifest.status }
        manifestItems.push(item)
        items.push(item)
        break
      }
      case 'approval.requested': {
        const approval = d.approval as ApprovalRecord | undefined
        if (!approval) break
        const item: ApprovalItem = { ...base, kind: 'approval', approval, resolved: false }
        approvalItems.set(approval.approval_id, item)
        items.push(item)
        const f = fact(approval.proposal_id)
        if (f) f.approval = approval
        break
      }
      case 'approval.resolved': {
        const approval = d.approval as ApprovalRecord | undefined
        if (!approval) break
        const item = approvalItems.get(approval.approval_id)
        if (item) {
          item.approval = approval
          item.resolved = true
        } else {
          const created: ApprovalItem = { ...base, kind: 'approval', approval, resolved: true }
          approvalItems.set(approval.approval_id, created)
          items.push(created)
        }
        const f = fact(approval.proposal_id)
        if (f) f.approval = approval
        break
      }
      case 'execution.committed': {
        const receipt = d.receipt as ExecutionReceipt | undefined
        if (!receipt) break
        receipts.push(receipt)
        committedManifestIds.add(receipt.manifest_id)
        items.push({ ...base, kind: 'commit', receipt })
        const f = fact(e.proposal_id)
        if (f) f.committed = true
        break
      }
      case 'execution.rejected': {
        rejections.push(e)
        const mid = str(d.manifest_id)
        if (mid) rejectedManifestIds.add(mid)
        items.push({ ...base, kind: 'rejected', event: e })
        const f = fact(e.proposal_id)
        if (f) f.rejectedExec = true
        break
      }
      case 'execution.duplicate': {
        items.push({ ...base, kind: 'duplicate', event: e })
        const f = fact(e.proposal_id)
        if (f) f.duplicate = true
        break
      }
      case 'replan':
        replans += 1
        items.push({ ...base, kind: 'replan', event: e })
        break
      case 'external.change':
        externals.push(e)
        items.push({ ...base, kind: 'external', event: e })
        break
      case 'run.finished': {
        finish = e
        const s = str(d.status)
        if (s) status = s as RunStatus
        items.push({ ...base, kind: 'finish', event: e })
        break
      }
      default:
        break
    }
  }

  for (const m of manifestItems) {
    if (committedManifestIds.has(m.manifest.manifest_id)) m.status = 'committed'
    else if (rejectedManifestIds.has(m.manifest.manifest_id)) m.status = 'stale'
  }

  let blockedProposals = 0
  for (const p of proposals) {
    const live = p.decisions.filter((x) => !x.shadow)
    p.blocker = live.find((x) => x.outcome === 'block' && x.decisive) ?? live.find((x) => x.outcome === 'block')
    p.unavailable = live.find((x) => x.outcome === 'unavailable')
    p.status = proposalStatus(p, facts.get(p.proposalId), useDetailFallback ? detailProposals?.get(p.proposalId)?.status : undefined)
    if (p.status === 'blocked') blockedProposals += 1
  }

  const approvals = Array.from(approvalItems.values()).map((a) => a.approval)
  const committedOrderIds = Array.from(new Set(receipts.flatMap((r) => r.changes.map((c) => c.row_id))))

  return {
    items,
    proposals,
    decisions,
    manifests,
    receipts,
    approvals,
    rejections,
    externals,
    steps,
    replans,
    commits: receipts.length,
    blockedProposals,
    status,
    plan,
    finish,
    committedOrderIds,
    annotations,
    planRequestedAt,
    planLatencyMs,
    matchedPolicies,
  }
}

/* ─── Human wording for proposals ─── */

export interface ActionCtx {
  /** Service account that owns an access grant, e.g. AG-77 -> svc-legacy-sync. */
  accessPrincipal: (grantId: string) => string | undefined
  /** Order ids a prepared manifest touches. */
  manifestRows: (manifestId: string) => string[]
}

export function argOrderIds(args: Record<string, unknown>, ctx?: ActionCtx): string[] {
  const ids = new Set<string>(strList(args.order_ids))
  if (Array.isArray(args.repairs)) {
    for (const r of args.repairs) {
      const id = str(rec(r).order_id)
      if (id) ids.add(id)
    }
  }
  const manifestId = str(args.manifest_id)
  if (manifestId && ctx) for (const id of ctx.manifestRows(manifestId)) ids.add(id)
  return Array.from(ids)
}

/** "Restore access grant AG-77 for svc-legacy-sync". */
export function actionSentence(tool: string, args: Record<string, unknown>, ctx: ActionCtx): string {
  const orders = argOrderIds(args, ctx)
  switch (tool) {
    case 'restore_access_grant': {
      const id = str(args.grant_id)
      const who = id ? ctx.accessPrincipal(id) : undefined
      return `Restore access grant${id ? ` ${id}` : ''}${who ? ` for ${who}` : ''}`
    }
    case 'prepare_repair_manifest':
      return orders.length ? `Prepare a repair for ${joinList(orders, 4)}` : 'Prepare a repair'
    case 'apply_repair_manifest':
      return orders.length ? `Apply the prepared repair to ${joinList(orders, 4)}` : 'Apply the prepared repair'
    case 'inspect_snapshot': {
      const tenant = str(args.tenant_id)
      return `Read the approved snapshot${tenant ? ` for ${tenantName(tenant)}` : ''}${orders.length ? ` (${joinList(orders, 4)})` : ''}`
    }
    case 'compare_current':
      return orders.length ? `Compare ${joinList(orders, 4)} with current data` : 'Compare orders with current data'
    case 'get_recovery_receipt':
      return 'Fetch the recovery receipt'
    default:
      return toolLabel(tool)
  }
}

export interface KeyArg {
  label: string
  value: string
  mono?: boolean
}

/** The few arguments worth showing under a proposal. Never raw JSON. */
export function keyArgs(args: Record<string, unknown>, ctx: ActionCtx): KeyArg[] {
  const out: KeyArg[] = []
  const tenant = str(args.tenant_id)
  if (tenant) out.push({ label: 'Tenant', value: tenantName(tenant) })
  const grantId = str(args.grant_id)
  if (grantId) out.push({ label: 'Access grant', value: grantId, mono: true })
  const orders = argOrderIds(args, ctx)
  if (orders.length) out.push({ label: orders.length === 1 ? 'Order' : 'Orders', value: orders.join(', '), mono: true })
  if (Array.isArray(args.repairs)) {
    const fields = new Set<string>()
    const proposed: string[] = []
    for (const r of args.repairs) {
      const rr = rec(r)
      strList(rr.fields).forEach((f) => fields.add(f))
      const pv = rec(rr.proposed_values)
      for (const [k, v] of Object.entries(pv)) proposed.push(`${str(rr.order_id) ?? 'Order'} ${fieldLabel(k).toLowerCase()} ${formatFieldValue(k, v)}`)
    }
    if (fields.size) out.push({ label: 'Fields', value: Array.from(fields).map(fieldLabel).join(', ') })
    if (proposed.length) out.push({ label: 'Proposed values', value: joinList(proposed, 2) })
  }
  const snapshot = str(args.snapshot_id)
  if (snapshot) out.push({ label: 'Snapshot', value: snapshot, mono: true })
  const manifestId = str(args.manifest_id)
  if (manifestId) out.push({ label: 'Repair', value: manifestId, mono: true })
  const reason = str(args.reason)
  if (reason) out.push({ label: 'Reason given', value: reason })
  return out.slice(0, 5)
}

/** The big label on a blocked card: "Blocked by ArmorIQ - signed plan binding". */
export function blockedByLabel(d: Decision): string {
  // A simulated decision names its simulated source, worded the same way as the layers source labels.
  if (d.simulated) return `Blocked by ${sourceLabel(d)}`
  switch (d.source) {
    case 'armoriq.sdk.plan_binding':
      return 'Blocked by ArmorIQ - signed plan binding'
    case 'armoriq.backend.enforce':
      return 'Blocked by ArmorIQ - policy'
    case 'armoriq.backend.token_issuance':
      return 'Blocked by ArmorIQ - plan issuance'
    case 'armoriq.backend.approval':
      return 'Blocked by ArmorIQ - delegation'
    case 'armoriq.offline_simulation':
      return 'Blocked by ArmorIQ (simulated) - local policy simulation'
    case 'rewindsafe.grant_scope':
      return 'Blocked by VeerIQ - grant scope'
    case 'rewindsafe.domain':
      return 'Blocked by VeerIQ - domain rule'
    case 'rewindsafe.approval':
      return 'Not approved by the second reviewer'
    case 'rewindsafe.tool_registry':
      return 'Blocked by VeerIQ - tool registry'
    case 'rewindsafe.lifecycle':
      return 'Blocked by VeerIQ - grant lifecycle'
    case 'postgres.privilege':
      return 'Blocked by PostgreSQL - privilege'
    case 'postgres.transaction':
      return 'Blocked by PostgreSQL - transaction check'
    default:
      return 'Blocked'
  }
}

export function isArmorIQ(d: Pick<Decision, 'layer'>): boolean {
  return d.layer === 'armoriq'
}

/** Short phrase for evidence sentences. Honest about which component decided. */
export function blockerPhrase(d: Decision): string {
  switch (d.source) {
    case 'armoriq.sdk.plan_binding':
      return 'ArmorIQ signed-plan binding'
    case 'armoriq.backend.enforce':
      return 'ArmorIQ policy'
    case 'armoriq.offline_simulation':
      return 'the simulated ArmorIQ policy (a local simulation, not the live service)'
    case 'rewindsafe.grant_scope':
      return 'the VeerIQ grant scope'
    case 'rewindsafe.domain':
      return 'a VeerIQ domain rule'
    case 'rewindsafe.approval':
      return 'the second reviewer'
    case 'rewindsafe.tool_registry':
    case 'rewindsafe.lifecycle':
      return 'the VeerIQ runtime'
    case 'postgres.privilege':
    case 'postgres.transaction':
      return 'PostgreSQL'
    default:
      return DECISION_FALLBACK
  }
}
const DECISION_FALLBACK = 'a protection layer'
