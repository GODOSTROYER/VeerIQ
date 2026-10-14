"""Recorded live evidence (``evidence/``) for the Proof board, sanitized before it leaves the server."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from rewindsafe.runtime import armoriq_gateway
from rewindsafe.runtime.canonical import redact_secrets

log = logging.getLogger("rewindsafe.api")

EVIDENCE_DIR = Path(__file__).resolve().parents[3] / "evidence"
EARLY_NOTE = "gate-a-early-live-2026-10-07.md"
_SECRET_KEY = re.compile(r"(token|secret|api[_-]?key|authorization|password|credential)", re.I)
_SECRET_VALUE = re.compile(r"(?<![A-Za-z0-9_])(ak_(live|test|claw)_|gsk_|sk-)[A-Za-z0-9_-]{6,}")
# Keys that look secret-ish but are public ids / counters we want to keep.
_KEEP_KEYS = {"token_id", "tokens", "input_tokens", "output_tokens", "total_tokens", "token_issuance"}


def sanitize(obj: Any) -> Any:
    """Drop secret-looking keys, mask key-shaped strings, then run the shared redactor."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            key = str(k)
            if key not in _KEEP_KEYS and _SECRET_KEY.search(key):
                continue
            out[key] = sanitize(v)
        return out
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if isinstance(obj, str):
        return _SECRET_VALUE.sub("[redacted]", obj)
    return obj


def _newest(pattern: str) -> Path | None:
    try:
        files = sorted(EVIDENCE_DIR.glob(pattern))
    except OSError:
        return None
    return files[-1] if files else None


def _load_json(pattern: str) -> dict[str, Any] | None:
    path = _newest(pattern)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("Could not parse evidence file %s", path, exc_info=True)
        return None
    cleaned = redact_secrets(sanitize(data))
    if isinstance(cleaned, dict):
        cleaned.setdefault("file", path.name)
    return cleaned


def _early_note() -> str | None:
    try:
        return redact_secrets((EVIDENCE_DIR / EARLY_NOTE).read_text(encoding="utf-8"))
    except OSError:
        return None


def _readiness() -> dict[str, Any] | None:
    try:
        fn = getattr(armoriq_gateway.get_gateway(), "readiness", None)
        return fn() if callable(fn) else None
    except Exception:
        log.warning("Gateway readiness unavailable", exc_info=True)
        return None


def live_evidence() -> dict[str, Any]:
    return {
        "gate_a": _load_json("gate-a-2*.json") or _load_json("gate-a-*.json"),
        "gate_a_early": _early_note(),
        "injection_eval": _load_json("injection-eval-*.json"),
        "readiness": _readiness(),
    }
