"""Server-Sent Events framing and the polling event stream.

Framing helpers are pure so they can be unit-tested without a server. The
stream polls ``events.list_events`` (sync, psycopg) via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from rewindsafe.contracts import RunEvent

POLL_INTERVAL_S = 0.3
HEARTBEAT_INTERVAL_S = 15.0
CLOSE_GRACE_S = 3.0
RETRY_MS = 3000
BATCH_LIMIT = 500

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_sse(event: RunEvent) -> str:
    """One ``run_event`` frame: ``id`` is the event sequence number."""
    payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.seq}\nevent: run_event\ndata: {payload}\n\n"


def heartbeat_frame() -> str:
    return ": heartbeat\n\n"


def retry_frame(ms: int = RETRY_MS) -> str:
    return f"retry: {ms}\n\n"


def parse_last_event_id(value: str | None) -> int | None:
    """Parse the ``Last-Event-ID`` header; garbage is treated as absent."""
    if value is None:
        return None
    try:
        parsed = int(value.strip())
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def resume_position(after: int, last_event_id: str | None) -> int:
    """Where to resume: the later of ``?after=`` and ``Last-Event-ID``."""
    return max(after, parse_last_event_id(last_event_id) or 0)


async def stream_events(
    list_fn: Callable[[str, int], list[RunEvent]],
    run_id: str,
    after_seq: int,
    *,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
    poll_interval: float = POLL_INTERVAL_S,
    heartbeat_interval: float = HEARTBEAT_INTERVAL_S,
    close_grace: float = CLOSE_GRACE_S,
    clock: Callable[[], float] = time.monotonic,
) -> AsyncIterator[str]:
    """Yield SSE frames until ``close_grace`` seconds after ``run.finished``."""
    yield retry_frame()
    last_seq = after_seq
    last_write = clock()
    finished_at: float | None = None
    while True:
        if is_disconnected is not None and await is_disconnected():
            return
        batch: list[Any] = await asyncio.to_thread(list_fn, run_id, last_seq)
        for event in batch:
            yield format_sse(event)
            last_seq = event.seq
            last_write = clock()
            if event.type == "run.finished" and finished_at is None:
                finished_at = clock()
        now = clock()
        if finished_at is not None and now - finished_at >= close_grace:
            return
        if now - last_write >= heartbeat_interval:
            yield heartbeat_frame()
            last_write = now
        if len(batch) >= BATCH_LIMIT:
            continue  # more backlog waiting; don't sleep
        await asyncio.sleep(poll_interval)
