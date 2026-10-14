"""Verification suite runner: executes every check sequentially and persists progress.

``run_suite(verification_id)`` writes ``runtime.verification_runs`` (status
``running`` -> ``passed``/``failed``), isolates each check (an exception is a
failed result, never a crash), and leaves a freshly reset fixture behind.

The API (W4) may pre-create the row; this module creates it when missing.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from psycopg.types.json import Jsonb

from rewindsafe.runtime import canonical, db
from rewindsafe.runtime.armoriq_gateway import get_gateway
from rewindsafe.verification import checks

# One suite at a time: every check resets the shared fixture.
_suite_lock = threading.Lock()


def _row_to_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return json.loads(canonical.canonical_json(row))


def get(verification_id: str) -> dict[str, Any] | None:
    with db.autocommit_connection() as conn:
        row = conn.execute(
            "SELECT * FROM runtime.verification_runs WHERE verification_id = %s", (verification_id,)
        ).fetchone()
    return _row_to_dict(row)


def latest() -> dict[str, Any] | None:
    with db.autocommit_connection() as conn:
        row = conn.execute("SELECT * FROM runtime.verification_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    return _row_to_dict(row)


def _summary(results: list[dict[str, Any]], total: int) -> dict[str, Any]:
    passed = sum(1 for r in results if r["passed"])
    by_layer: dict[str, int] = {}
    for r in results:
        by_layer[r["layer_actual"]] = by_layer.get(r["layer_actual"], 0) + 1
    return {"total": total, "completed": len(results), "passed": passed,
            "failed": len(results) - passed, "by_layer": by_layer}


def _save(verification_id: str, status: str, results: list[dict[str, Any]], summary: dict[str, Any],
          finished: bool) -> None:
    with db.autocommit_connection() as conn:
        conn.execute(
            "UPDATE runtime.verification_runs SET status = %s, results = %s, summary = %s,"
            " finished_at = CASE WHEN %s THEN now() ELSE NULL END WHERE verification_id = %s",
            (status, Jsonb(results), Jsonb(summary), finished, verification_id),
        )


def run_suite(verification_id: str | None = None) -> dict[str, Any]:
    """Run every check; returns the final ``runtime.verification_runs`` row as a dict."""
    verification_id = verification_id or canonical.new_id("ver")
    mode = get_gateway().describe()["mode"]
    total = len(checks.ALL_CHECK_IDS)
    with _suite_lock:
        with db.autocommit_connection() as conn:
            conn.execute(
                "INSERT INTO runtime.verification_runs (verification_id, status, enforcement_mode)"
                " VALUES (%s, 'running', %s) ON CONFLICT (verification_id) DO UPDATE SET"
                " status = 'running', enforcement_mode = EXCLUDED.enforcement_mode, results = '[]'::jsonb,"
                " summary = '{}'::jsonb, finished_at = NULL",
                (verification_id, mode),
            )
        results: list[dict[str, Any]] = []
        try:
            for check_id in checks.ALL_CHECK_IDS:
                results.append(checks.run_check(check_id))
                _save(verification_id, "running", results, _summary(results, total), finished=False)
            summary = _summary(results, total)
            _save(verification_id, "passed" if summary["failed"] == 0 else "failed", results, summary, True)
        except BaseException as exc:  # noqa: BLE001 - never leave a row stuck in 'running'
            summary = _summary(results, total)
            summary["error"] = f"{type(exc).__name__}: {exc}"[:300]
            _save(verification_id, "failed", results, summary, True)
            raise
        finally:
            try:
                checks.reset_fixture_state()  # leave a fresh fixture for the next demo
            except Exception:  # noqa: BLE001
                pass
    return get(verification_id) or {}
