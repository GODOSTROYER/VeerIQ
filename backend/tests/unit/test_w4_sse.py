"""Pure SSE helpers and the polling stream (no server, no database)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from rewindsafe.api import sse
from rewindsafe.contracts import Actor, RunEvent

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def ev(seq: int, type_: str = "agent.note") -> RunEvent:
    return RunEvent(seq=seq, run_id="run_1", ts=NOW, type=type_, actor=Actor.AGENT, title="t", detail="line1\nline2")


def collect(gen, limit=None):
    async def run():
        out = []
        async for frame in gen:
            out.append(frame)
            if limit and len(out) >= limit:
                break
        return out

    return asyncio.run(run())


def test_format_sse_has_id_event_data_and_single_line_json():
    frame = sse.format_sse(ev(7))
    lines = frame.split("\n")
    assert lines[0] == "id: 7" and lines[1] == "event: run_event"
    assert lines[2].startswith("data: ") and lines[3] == "" and lines[4] == ""
    payload = json.loads(lines[2][len("data: "):])
    assert payload["seq"] == 7 and payload["detail"] == "line1\nline2"  # newlines escaped, not raw


def test_parse_last_event_id():
    assert sse.parse_last_event_id("12") == 12
    assert sse.parse_last_event_id(" 5 ") == 5
    assert sse.parse_last_event_id("abc") is None
    assert sse.parse_last_event_id("-3") is None
    assert sse.parse_last_event_id(None) is None
    assert sse.resume_position(0, "9") == 9
    assert sse.resume_position(15, "9") == 15
    assert sse.resume_position(2, "junk") == 2


def test_stream_replays_then_closes_after_grace():
    items = [ev(1), ev(2), ev(3, "run.finished")]
    frames = collect(
        sse.stream_events(
            lambda rid, after: [e for e in items if e.seq > after], "run_1", 0,
            poll_interval=0.005, close_grace=0.03,
        )
    )
    assert frames[0].startswith("retry:")
    assert [f.splitlines()[0] for f in frames[1:]] == ["id: 1", "id: 2", "id: 3"]


def test_stream_delivers_late_events_inside_grace_window():
    state = {"calls": 0}

    def list_fn(run_id, after):
        state["calls"] += 1
        if state["calls"] == 1:
            return [ev(1, "run.finished")]
        if state["calls"] == 3:
            return [ev(2, "state.changed")]
        return []

    frames = collect(sse.stream_events(list_fn, "run_1", 0, poll_interval=0.005, close_grace=0.1))
    assert [f.splitlines()[0] for f in frames[1:]] == ["id: 1", "id: 2"]


def test_heartbeat_comment_when_idle():
    frames = collect(
        sse.stream_events(lambda rid, after: [], "run_1", 0, poll_interval=0.005, heartbeat_interval=0.02),
        limit=3,
    )
    assert frames[0].startswith("retry:") and frames[1] == ": heartbeat\n\n"


def test_stream_stops_when_client_disconnects():
    calls = {"n": 0}

    async def disconnected():
        calls["n"] += 1
        return calls["n"] > 2

    frames = collect(
        sse.stream_events(lambda rid, after: [], "run_1", 0, is_disconnected=disconnected, poll_interval=0.005)
    )
    assert frames == [sse.retry_frame()]
