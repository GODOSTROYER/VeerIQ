import { useCallback, useEffect, useState } from 'react'
import type { RunEvent } from '@/api/types'

/** Re-renders on an interval so countdowns stay fresh. Pass 0 to stop ticking. */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!intervalMs) return
    setNow(Date.now())
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return now
}

export const REPLAY_SPEED = 4
/** Events that change nothing visible in the timeline are replayed almost instantly. */
const SILENT_TYPES = new Set(['run.created', 'run.status', 'state.changed', 'telemetry.delivery', 'tool.result'])
const MIN_VISIBLE_MS = 260
const MAX_GAP_MS = 1400
const SILENT_MS = 30

export interface ReplayState {
  active: boolean
  playing: boolean
  /** How many events are currently shown. */
  cursor: number
  total: number
  start: () => void
  stop: () => void
  toggle: () => void
  skipToEnd: () => void
}

/**
 * Re-animates a finished run's event stream from seq 0 at 4x the recorded pace.
 * Gaps between events are the recorded gaps divided by the speed, clamped so a long wait
 * (for example a reviewer approving) does not stall the demo.
 */
export function useReplay(events: readonly RunEvent[]): ReplayState {
  const [active, setActive] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [cursor, setCursor] = useState(0)
  const total = events.length

  useEffect(() => {
    if (!active || !playing) return
    if (cursor >= total) {
      // Recorded events can hydrate in batches. Reaching a partial batch is
      // a wait, not the end of the replay.
      if (events.some(event => event.type === 'run.finished')) setPlaying(false)
      return
    }
    const next = events[cursor]
    const prev = cursor > 0 ? events[cursor - 1] : null
    let delay: number
    if (SILENT_TYPES.has(next.type)) {
      delay = SILENT_MS
    } else {
      const gap = prev ? (Date.parse(next.ts) - Date.parse(prev.ts)) / REPLAY_SPEED : 500
      delay = Math.min(MAX_GAP_MS, Math.max(MIN_VISIBLE_MS, Number.isFinite(gap) ? gap : MIN_VISIBLE_MS))
    }
    const id = window.setTimeout(() => setCursor((c) => c + 1), delay)
    return () => window.clearTimeout(id)
  }, [active, playing, cursor, total, events])

  const start = useCallback(() => {
    setCursor(0)
    setActive(true)
    setPlaying(true)
  }, [])
  const stop = useCallback(() => {
    setActive(false)
    setPlaying(false)
    setCursor(0)
  }, [])
  const toggle = useCallback(() => {
    setCursor((c) => (c >= total ? 0 : c))
    setPlaying((p) => !p)
  }, [total])
  const skipToEnd = useCallback(() => {
    setCursor(total)
    setPlaying(false)
  }, [total])

  return { active, playing, cursor, total, start, stop, toggle, skipToEnd }
}

/** True when the viewport is at least `px` wide. Lets a layout render one variant instead of hiding a duplicate. */
export function useMinWidth(px: number): boolean {
  const query = `(min-width: ${px}px)`
  const [matches, setMatches] = useState(() => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(query).matches : true))
  useEffect(() => {
    if (!window.matchMedia) return
    const mq = window.matchMedia(query)
    const on = () => setMatches(mq.matches)
    on()
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [query])
  return matches
}
