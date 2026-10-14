/**
 * Tiny event bus. Query hooks subscribe to "tags"; anything that learns the world
 * changed (an SSE `state.changed` event, a successful POST) invalidates a tag and
 * every hook carrying that tag refetches. No heavy data library needed.
 */

type Listener = (tag: string) => void

const listeners = new Set<Listener>()

export const TAGS = {
  appState: 'app-state',
  checks: 'protected-checks',
  diff: 'snapshot-diff',
  runs: 'runs',
  approvals: 'approvals',
  status: 'system-status',
  metrics: 'metrics',
  verification: 'verification',
  run: (id: string) => `run:${id}`,
} as const

export function invalidate(...tags: string[]): void {
  for (const tag of tags) for (const l of Array.from(listeners)) l(tag)
}

export function subscribeInvalidation(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Everything that derives from application data. */
export function invalidateAppData(): void {
  invalidate(TAGS.appState, TAGS.checks, TAGS.diff)
}
