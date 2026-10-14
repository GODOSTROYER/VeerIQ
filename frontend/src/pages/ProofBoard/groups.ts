import type { VerificationResult } from '@/api/types'

export type GroupId = 'authority' | 'data' | 'concurrency' | 'approvals' | 'failure' | 'other'

export interface GroupMeta {
  id: GroupId
  title: string
  blurb: string
}

export const GROUPS: GroupMeta[] = [
  { id: 'authority', title: 'Authority boundary', blurb: 'The agent cannot do what its grant and the signed plan do not allow.' },
  { id: 'data', title: 'Data correctness', blurb: 'Only snapshot values are written, and today’s decisions survive the repair.' },
  { id: 'concurrency', title: 'Concurrency and retries', blurb: 'Races, replays and double submits never write twice.' },
  { id: 'approvals', title: 'Approvals', blurb: 'High-value repairs need a second person, bound to the exact payload.' },
  { id: 'failure', title: 'Failure handling', blurb: 'When something is expired, unreachable or reset, the system fails closed.' },
  { id: 'other', title: 'Other checks', blurb: 'Checks the suite reported that do not fit a named group.' },
]

/** Ordered rules: the first matching pattern wins. Matching is on the check id and guarantee text. */
const RULES: [GroupId, RegExp][] = [
  ['approvals', /approv|review|reviewer|substitut/],
  ['concurrency', /duplicate|idempot|key_reuse|concurren|double|race|stale|retry|replay/],
  ['failure', /unavailable|expire|reset|timeout|fail|positive_control|audit|telemetry/],
  ['data', /invented|snapshot_value|tombstone|resurrect|later_update|overwrite|digest|manifest|clean|repair|tenant_isolation|beacon|revoked_access/],
  ['authority', /off_plan|plan|wrong_tenant|tenant|authority|column|remint|wider|grant|privilege|scope|privileg/],
]

export function groupOf(result: VerificationResult): GroupId {
  const explicit = (result as unknown as { group?: unknown }).group
  if (typeof explicit === 'string') {
    const norm = explicit.toLowerCase().replace(/\s*&\s*/g, ' and ')
    const hit = GROUPS.find((g) => g.id === norm || g.title.toLowerCase() === norm)
    if (hit) return hit.id
  }
  const hay = `${result.check_id} ${result.guarantee}`.toLowerCase()
  for (const [id, re] of RULES) if (re.test(hay)) return id
  return 'other'
}
