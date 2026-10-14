"""Background execution of the verification suite (one at a time)."""

from __future__ import annotations

import importlib
import json
import logging
import threading
from typing import Any

from rewindsafe.runtime import canonical, db

log = logging.getLogger("rewindsafe.api")

_lock = threading.Lock()
_current_id: str | None = None


def _suite():
    return importlib.import_module("rewindsafe.verification.suite")


def current_id() -> str | None:
    with _lock:
        return _current_id


def start() -> str | None:
    """Start the suite in a daemon thread; returns its id, or None if one is already running."""
    global _current_id
    with _lock:
        if _current_id is not None:
            return None
        verification_id = canonical.new_id("ver")
        _current_id = verification_id
    try:  # the suite resets the fixture ~25 times: stop live user runs first (they would be cancelled anyway)
        from rewindsafe.api import deps

        deps.cancel_active_runs("Verification suite started")
    except Exception:
        log.warning("Could not cancel active runs before verification", exc_info=True)
    thread = threading.Thread(
        target=_run, args=(verification_id,), name=f"verification-{verification_id}", daemon=True
    )
    thread.start()
    return verification_id


def _run(verification_id: str) -> None:
    global _current_id
    try:
        _suite().run_suite(verification_id)
    except Exception as exc:
        log.exception("Verification suite crashed (%s)", verification_id)
        _mark_failed(verification_id, f"{type(exc).__name__}: {exc}")
    finally:
        with _lock:
            _current_id = None


def _mark_failed(verification_id: str, error: str) -> None:
    try:
        with db.transaction() as conn:
            updated = conn.execute(
                "UPDATE runtime.verification_runs SET status = 'failed', finished_at = now(), "
                "summary = summary || %s::jsonb WHERE verification_id = %s",
                (json.dumps({"error": error}), verification_id),
            ).rowcount
            if not updated:
                conn.execute(
                    "INSERT INTO runtime.verification_runs (verification_id, status, enforcement_mode, finished_at, summary) "
                    "VALUES (%s, 'failed', 'unknown', now(), %s::jsonb)",
                    (verification_id, json.dumps({"error": error})),
                )
    except Exception:
        log.exception("Could not record verification failure for %s", verification_id)


def get(verification_id: str) -> dict[str, Any] | None:
    found = _suite().get(verification_id)
    if found is None and verification_id == current_id():
        # Started but the suite has not written its row yet.
        return {"verification_id": verification_id, "status": "running", "results": [], "summary": {}}
    return found


def latest() -> dict[str, Any] | None:
    return _suite().latest()
