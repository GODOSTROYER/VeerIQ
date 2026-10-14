"""Authenticated read-only access to the newest reliability evaluation artifact."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query

from rewindsafe.agent.reliability_eval import _failure_cause, _summarize
from rewindsafe.api import auth, evidence
from rewindsafe.api.errors import not_found
from rewindsafe.config import REPO_ROOT
from rewindsafe.contracts import Identity

log = logging.getLogger("rewindsafe.api")
router = APIRouter(prefix="/api/evidence", tags=["evidence"])
EVIDENCE_DIR = REPO_ROOT / "evidence"
_ARTIFACT_NAME = re.compile(r"reliability-\d{8}T\d{6}Z\.json\Z")


def _latest_artifact() -> Path | None:
    try:
        paths = list(EVIDENCE_DIR.glob("reliability-*.json"))
        return max(paths, key=lambda p: (p.stat().st_mtime_ns, p.name)) if paths else None
    except OSError:
        log.warning("Could not list reliability evidence files", exc_info=True)
        return None


def _catalog() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        paths = sorted(
            EVIDENCE_DIR.glob("reliability-*.json"),
            key=lambda p: (p.stat().st_mtime_ns, p.name),
            reverse=True,
        )
    except OSError:
        log.warning("Could not list reliability evidence files", exc_info=True)
        return entries
    for path in paths:
        if not _ARTIFACT_NAME.fullmatch(path.name):
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("Could not parse reliability evidence file %s", path.name, exc_info=True)
            continue
        if not isinstance(raw, dict):
            continue
        rows = raw.get("trials", []) if isinstance(raw.get("trials"), list) else []
        requested = int(raw.get("requested_trials", 0) or 0)
        finished_at = raw.get("finished_at")
        completed = sum(row.get("status") == "completed" for row in rows if isinstance(row, dict))
        if finished_at is None and requested > 0 and completed >= requested:
            finished_at = raw.get("updated_at")
        entries.append(
            {
                "file": path.name,
                "requested_trials": requested,
                "recorded_trials": len(rows),
                "finished_at": finished_at,
            }
        )
    return entries


def _normalize_for_api(raw: dict[str, Any]) -> dict[str, Any]:
    """Enrich older artifacts without changing the source file or asserting unknown safety as zero."""
    payload = dict(raw)
    trials = [dict(row) for row in payload.get("trials", []) if isinstance(row, dict)]
    for row in trials:
        if "evidence_complete" not in row:
            row["evidence_complete"] = False
        if not row["evidence_complete"] or row.get("forbidden_effects") is None:
            row["forbidden_effects"] = None
            row["forbidden_effect_details"] = None
            row["failed"] = True
        if "failure_cause" not in row:
            row["failure_cause"] = _failure_cause(
                failure=row.get("failure"),
                status=str(row.get("outcome") or "failed"),
                evidence_complete=bool(row["evidence_complete"]),
                forbidden_effects=row.get("forbidden_effects"),
            )
        row.setdefault("attempted_restore", None)
        row.setdefault("attempted_cross_tenant", None)
        row.setdefault("forbidden_attempts", None)
        row.setdefault("completed", False)
        # Legacy rows predate bounded deterministic recovery assistance.
        row.setdefault("recovery_mode", "llm_only")
        row.setdefault("recovery_fallback", None)
        row.setdefault("raw_llm_completed", bool(row.get("completed")))
        row.setdefault("assisted_completed", False)
        row.setdefault("llm_failure_cause", None)
        row.setdefault("tokens", None)
        row.setdefault("latency_s", None)
        row.setdefault("failure", None)
        row.setdefault("failed", not bool(row.get("completed")))
    payload["trials"] = trials
    payload.pop("_path", None)
    payload["summary"] = {}
    _summarize(payload)
    requested = int(payload.get("requested_trials", 0) or 0)
    done = sum(row.get("status") == "completed" for row in trials)
    payload.setdefault("finished_at", payload.get("updated_at") if requested and done >= requested else None)
    payload["status"] = "completed" if requested and done >= requested else "in_progress"
    return evidence.sanitize(payload)


@router.get("/reliability")
def latest_reliability(
    file: str | None = Query(default=None), _: Identity = Depends(auth.current_identity)
) -> dict[str, Any]:
    """Return a selected or latest sanitized artifact without changing its source file."""
    if file is not None:
        if not _ARTIFACT_NAME.fullmatch(file):
            raise not_found("Reliability evidence is not available.")
        path = EVIDENCE_DIR / file
        try:
            if path.resolve().parent != EVIDENCE_DIR.resolve() or not path.is_file():
                raise not_found("Reliability evidence is not available.")
        except OSError:
            raise not_found("Reliability evidence is not available.")
    else:
        path = _latest_artifact()
    if path is None:
        raise not_found("Reliability evidence is not available yet.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("Could not parse reliability evidence file %s", path.name, exc_info=True)
        raise not_found("Reliability evidence is not available yet.")
    if not isinstance(raw, dict):
        raise not_found("Reliability evidence is not available yet.")
    response = _normalize_for_api(raw)
    response["file"] = path.name
    return response


@router.get("/reliability/catalog")
def reliability_catalog(_: Identity = Depends(auth.current_identity)) -> dict[str, Any]:
    """List safe artifact selectors and counts; never expose raw trial content here."""
    return {"artifacts": _catalog()}
