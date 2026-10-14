import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from './client'
import { invalidate, invalidateAppData, subscribeInvalidation, TAGS } from './bus'
import { clearQueryCache, queryCache } from './cache'
import { openRunStream, type StreamState } from './sse'
import {
  TERMINAL_RUN_STATUSES,
  type AppState,
  type ApprovalWithPreview,
  type InvariantCheck,
  type LiveEvidence,
  type Metrics,
  type Run,
  type RunDetail,
  type RunEvent,
  type ScenarioSpec,
  type SnapshotDiffRow,
  type SystemStatus,
  type VerificationRun,
} from './types'

export { useSession, SessionProvider, useIdentities } from './session'
export { invalidate, invalidateAppData, TAGS } from './bus'

// ─── Minimal query hook ────────────────────────────────────────────────────

const cache = queryCache
export { clearQueryCache }

export interface QueryOptions {
  /** When false the query does not run (e.g. waiting for an id). */
  enabled?: boolean
  /** Invalidation tags: any `invalidate(tag)` triggers a refetch. */
  tags?: string[]
  /** Poll interval in ms; false/undefined disables polling. */
  refetchInterval?: number | false
}

export interface QueryResult<T> {
  data: T | undefined
  error: Error | undefined
  /** True only while there is nothing to show yet. */
  loading: boolean
  /** True during any in-flight request, including background refreshes. */
  fetching: boolean
  refetch: () => Promise<void>
}

export function useQuery<T>(path: string | null, options: QueryOptions = {}): QueryResult<T> {
  const { enabled = true, tags, refetchInterval } = options
  const active = enabled && path !== null
  const [data, setData] = useState<T | undefined>(() => (path ? (cache.get(path) as T | undefined) : undefined))
  const [error, setError] = useState<Error | undefined>(undefined)
  const [fetching, setFetching] = useState<boolean>(active)
  const seq = useRef(0)
  const tagsKey = (tags ?? []).join('|')

  // Reset local state when the key changes.
  useEffect(() => {
    setData(path ? (cache.get(path) as T | undefined) : undefined)
    setError(undefined)
  }, [path])

  const run = useCallback(async () => {
    if (!active || path === null) return
    const mine = ++seq.current
    setFetching(true)
    try {
      const result = await api.get<T>(path)
      if (mine !== seq.current) return
      cache.set(path, result)
      setData(result)
      setError(undefined)
    } catch (err) {
      if (mine !== seq.current) return
      setError(err as Error)
    } finally {
      if (mine === seq.current) setFetching(false)
    }
  }, [active, path])

  useEffect(() => {
    void run()
    return () => {
      seq.current += 1
    }
  }, [run])

  // Tag invalidation.
  useEffect(() => {
    if (!active || !tagsKey) return
    const mine = new Set(tagsKey.split('|'))
    return subscribeInvalidation((tag) => {
      if (mine.has(tag)) void run()
    })
  }, [active, tagsKey, run])

  // Optional polling (paused while the tab is hidden).
  useEffect(() => {
    if (!active || !refetchInterval) return
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') void run()
    }, refetchInterval)
    return () => window.clearInterval(id)
  }, [active, refetchInterval, run])

  return { data, error, loading: active && data === undefined && error === undefined, fetching, refetch: run }
}

// ─── Domain hooks ──────────────────────────────────────────────────────────

export function useSystemStatus(): QueryResult<SystemStatus> {
  return useQuery<SystemStatus>('/system/status', { tags: [TAGS.status], refetchInterval: 15_000 })
}

export function useLiveEvidence(enabled = true): QueryResult<LiveEvidence> {
  return useQuery<LiveEvidence>('/evidence/live', { enabled, tags: [TAGS.status] })
}

export function useAppState(enabled = true): QueryResult<AppState> {
  return useQuery<AppState>('/app/state', { enabled, tags: [TAGS.appState] })
}

export function useProtectedChecks(enabled = true): QueryResult<InvariantCheck[]> {
  return useQuery<InvariantCheck[]>('/app/protected-checks', { enabled, tags: [TAGS.checks] })
}

export function useSnapshotDiff(enabled = true): QueryResult<SnapshotDiffRow[]> {
  return useQuery<SnapshotDiffRow[]>('/app/snapshot-diff', { enabled, tags: [TAGS.diff, TAGS.appState] })
}

export function useScenarios(): QueryResult<ScenarioSpec[]> {
  const q = useQuery<ScenarioSpec[]>('/scenarios')
  const sorted = useMemo(() => (q.data ? [...q.data].sort((a, b) => a.order - b.order) : undefined), [q.data])
  return { ...q, data: sorted }
}

export function useRuns(enabled = true): QueryResult<Run[]> {
  return useQuery<Run[]>('/runs', { enabled, tags: [TAGS.runs], refetchInterval: 8000 })
}

export function useRun(runId: string | undefined): QueryResult<RunDetail> {
  const q = useQuery<RunDetail>(runId ? `/runs/${runId}` : null, {
    tags: runId ? [TAGS.run(runId)] : [],
  })
  const live = q.data ? !TERMINAL_RUN_STATUSES.includes(q.data.run.status) : false
  // Safety net while a run is live: the SSE stream normally triggers refetches first.
  const { refetch } = q
  useEffect(() => {
    if (!live) return
    const id = window.setInterval(() => void refetch(), 6000)
    return () => window.clearInterval(id)
  }, [live, refetch])
  return q
}

export function useApprovals(status?: string, enabled = true): QueryResult<ApprovalWithPreview[]> {
  return useQuery<ApprovalWithPreview[]>(`/approvals${status ? `?status=${encodeURIComponent(status)}` : ''}`, {
    enabled,
    tags: [TAGS.approvals],
    refetchInterval: 5000,
  })
}

export function useMetrics(enabled = true): QueryResult<Metrics> {
  return useQuery<Metrics>('/metrics', { enabled, tags: [TAGS.metrics] })
}

export interface VerificationHook {
  run: VerificationRun | null | undefined
  loading: boolean
  error: Error | undefined
  starting: boolean
  running: boolean
  start: () => Promise<void>
  refetch: () => Promise<void>
}

/** Latest verification run plus a `start()` that triggers the suite and tracks it to completion. */
export function useVerification(): VerificationHook {
  const latest = useQuery<VerificationRun | null>('/verification/latest', { tags: [TAGS.verification] })
  const [activeId, setActiveId] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<Error | undefined>(undefined)
  const tracked = useQuery<VerificationRun>(activeId ? `/verification/${activeId}` : null, {
    refetchInterval: activeId ? 1500 : false,
  })

  const finishedId = tracked.data && tracked.data.status !== 'running' ? tracked.data.verification_id : null
  const { refetch: refetchLatest } = latest
  useEffect(() => {
    if (!finishedId) return
    setActiveId(null)
    void refetchLatest()
    invalidate(TAGS.metrics)
  }, [finishedId, refetchLatest])

  const start = useCallback(async () => {
    setStarting(true)
    setStartError(undefined)
    try {
      const res = await api.post<{ verification_id: string }>('/verification/run')
      setActiveId(res.verification_id)
    } catch (err) {
      setStartError(err as Error)
    } finally {
      setStarting(false)
    }
  }, [])

  const running = activeId !== null || latest.data?.status === 'running'
  return {
    run: activeId && tracked.data ? tracked.data : latest.data,
    loading: latest.loading,
    error: startError ?? latest.error,
    starting,
    running,
    start,
    refetch: latest.refetch,
  }
}

// ─── Live run events ───────────────────────────────────────────────────────

const REFETCH_RUN_ON = new Set([
  'run.status',
  'plan.bound',
  'plan.bind_failed',
  'agent.proposal',
  'decision',
  'manifest.prepared',
  'approval.requested',
  'approval.resolved',
  'execution.committed',
  'execution.rejected',
  'execution.duplicate',
  'external.change',
  'run.finished',
])

export interface RunEventsResult {
  events: RunEvent[]
  connection: StreamState
  finished: boolean
  /** Set when the feed stopped for good (signed out, wrong tenant, run not found). */
  streamError: ApiError | null
}

/**
 * Streams a run's events (SSE with resume, backoff and polling fallback), keeps
 * them de-duplicated by seq, and fans events out as cache invalidations:
 * `state.changed` refreshes app data; run-shaping events refresh `useRun`.
 */
export function useRunEvents(runId: string | undefined): RunEventsResult {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [connection, setConnection] = useState<StreamState>('connecting')
  const [finished, setFinished] = useState(false)
  const [streamError, setStreamError] = useState<ApiError | null>(null)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    setEvents([])
    setFinished(false)
    setStreamError(null)
    if (!runId) return
    setConnection('connecting')

    const scheduleRunRefetch = () => {
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => invalidate(TAGS.run(runId), TAGS.runs), 200)
    }

    const close = openRunStream({
      runId,
      onState: setConnection,
      onFinished: () => setFinished(true),
      onError: setStreamError,
      onEvents: (incoming) => {
        setEvents((prev) => {
          const known = new Set(prev.map((e) => e.seq))
          const merged = [...prev, ...incoming.filter((e) => !known.has(e.seq))]
          return merged.sort((a, b) => a.seq - b.seq)
        })
        let touchRun = false
        for (const e of incoming) {
          if (e.type === 'state.changed' || e.type === 'execution.committed') invalidateAppData()
          if (e.type === 'approval.requested' || e.type === 'approval.resolved') invalidate(TAGS.approvals)
          if (REFETCH_RUN_ON.has(e.type)) touchRun = true
        }
        if (touchRun) scheduleRunRefetch()
      },
    })
    return () => {
      window.clearTimeout(timer.current)
      close()
    }
  }, [runId])

  return { events, connection, finished, streamError }
}

/** True when an error is a 401 (session missing or expired). */
export function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.isUnauthorized
}
