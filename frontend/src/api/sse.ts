import { api, API_BASE, ApiError } from './client'
import type { RunEvent } from './types'

export type StreamState = 'connecting' | 'live' | 'reconnecting' | 'polling' | 'closed'

export interface RunStreamOptions {
  runId: string
  /** Highest seq already known (resume point). */
  afterSeq?: number
  onEvents: (events: RunEvent[]) => void
  onState: (state: StreamState) => void
  /** Called once the stream has seen run.finished (stream then closes by itself). */
  onFinished?: () => void
  /** Called when the feed cannot continue for a reason retrying will not fix (401/403/404). */
  onError?: (e: ApiError) => void
}

const isFatal = (err: unknown): err is ApiError =>
  err instanceof ApiError && (err.status === 401 || err.status === 403 || err.status === 404)

const BACKOFF_MS = [800, 1600, 3200, 6400, 10_000]
const MAX_SSE_FAILURES_BEFORE_POLLING = 3
const POLL_INTERVAL_MS = 2000
const SSE_RETRY_WHILE_POLLING_MS = 30_000

/**
 * Subscribes to a run's event stream.
 * - Resumes from the last seen seq (?after=) after every drop.
 * - Reconnects with exponential backoff.
 * - De-duplicates by seq (EventSource replays, polling overlap).
 * - After repeated SSE failures it falls back to polling /events/list and keeps
 *   retrying SSE in the background.
 * Returns an unsubscribe function.
 */
export function openRunStream(opts: RunStreamOptions): () => void {
  let lastSeq = opts.afterSeq ?? 0
  let source: EventSource | null = null
  let stopped = false
  let finished = false
  let failures = 0
  let retryTimer: number | undefined
  let pollTimer: number | undefined
  let sseRetryTimer: number | undefined
  let polling = false

  const deliver = (incoming: RunEvent[]) => {
    const fresh = incoming.filter((e) => e.seq > lastSeq).sort((a, b) => a.seq - b.seq)
    if (fresh.length === 0) return
    lastSeq = fresh[fresh.length - 1].seq
    opts.onEvents(fresh)
    if (fresh.some((e) => e.type === 'run.finished')) {
      finished = true
      opts.onFinished?.()
    }
  }

  const closeSource = () => {
    if (source) {
      source.close()
      source = null
    }
  }

  const stopPolling = () => {
    polling = false
    window.clearTimeout(pollTimer)
    window.clearTimeout(sseRetryTimer)
  }

  const finish = () => {
    stopped = true
    closeSource()
    stopPolling()
    window.clearTimeout(retryTimer)
    opts.onState('closed')
  }

  const poll = async () => {
    if (stopped || !polling) return
    try {
      const events = await api.get<RunEvent[]>(`/runs/${opts.runId}/events/list?after=${lastSeq}`)
      deliver(events)
    } catch (err) {
      if (isFatal(err)) {
        opts.onError?.(err)
        return finish()
      }
      /* otherwise keep polling; the UI already shows the degraded state */
    }
    if (finished) return finish()
    if (!stopped && polling) pollTimer = window.setTimeout(poll, POLL_INTERVAL_MS)
  }

  const startPolling = () => {
    if (polling || stopped) return
    polling = true
    opts.onState('polling')
    void poll()
    // Keep probing SSE in the background so we return to live updates when possible.
    sseRetryTimer = window.setTimeout(() => {
      if (stopped || finished) return
      stopPolling()
      failures = 0
      connect()
    }, SSE_RETRY_WHILE_POLLING_MS)
  }

  const scheduleReconnect = () => {
    closeSource()
    if (stopped) return
    if (finished) return finish()
    failures += 1
    if (failures >= MAX_SSE_FAILURES_BEFORE_POLLING) {
      startPolling()
      return
    }
    opts.onState('reconnecting')
    const delay = BACKOFF_MS[Math.min(failures - 1, BACKOFF_MS.length - 1)]
    retryTimer = window.setTimeout(connect, delay)
  }

  function connect() {
    if (stopped) return
    closeSource()
    opts.onState(failures === 0 ? 'connecting' : 'reconnecting')
    try {
      source = new EventSource(`${API_BASE}/runs/${opts.runId}/events?after=${lastSeq}`, { withCredentials: true })
    } catch {
      scheduleReconnect()
      return
    }
    source.onopen = () => {
      failures = 0
      opts.onState('live')
    }
    source.addEventListener('run_event', (msg) => {
      try {
        deliver([JSON.parse((msg as MessageEvent<string>).data) as RunEvent])
      } catch {
        /* ignore malformed frame */
      }
    })
    source.onerror = () => {
      // The server closes the stream ~3s after run.finished; that is not a failure.
      if (finished) return finish()
      scheduleReconnect()
    }
  }

  // Catch up on anything missed before the stream opened, then stream live.
  void api
    .get<RunEvent[]>(`/runs/${opts.runId}/events/list?after=${lastSeq}`)
    .then((events) => !stopped && deliver(events))
    .catch((err) => {
      if (isFatal(err)) {
        opts.onError?.(err)
        finish()
      }
    })
    .finally(() => {
      if (stopped) return
      if (finished) return finish()
      connect()
    })

  return () => {
    stopped = true
    closeSource()
    stopPolling()
    window.clearTimeout(retryTimer)
  }
}
