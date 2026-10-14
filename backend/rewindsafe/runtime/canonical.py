"""Canonical JSON, digests, ids, clocks and secret redaction.

``canonical_json`` is the single serialization used for every digest in the
system (grant digest, manifest digest, payload digest, receipt digest), so a
digest computed anywhere can be recomputed anywhere.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(UTC)


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)  # naive datetimes are treated as UTC
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _normalize(obj: Any) -> Any:
    """Recursively convert ``obj`` to plain JSON types, deterministically."""
    if obj is None or isinstance(obj, (bool, str)):
        # str-subclass enums are handled below, before this branch is reached for them
        if isinstance(obj, Enum):
            return _normalize(obj.value)
        return obj
    if isinstance(obj, Enum):
        return _normalize(obj.value)
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError("NaN/Infinity cannot be canonicalized")
        return obj
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return _iso_utc(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, BaseModel):
        return _normalize(obj.model_dump(mode="json"))
    if isinstance(obj, dict):
        return {_key(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted((_normalize(v) for v in obj), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(obj, (bytes, bytearray)):
        return obj.hex()
    raise TypeError(f"Object of type {type(obj).__name__} is not canonicalizable")


def _key(k: Any) -> str:
    if isinstance(k, Enum):
        k = k.value
    if isinstance(k, str):
        return k
    if isinstance(k, (int, float, bool)) or k is None:
        return json.dumps(k)
    raise TypeError(f"Unsupported dict key type {type(k).__name__}")


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, compact separators, non-ASCII preserved."""
    return json.dumps(
        _normalize(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(obj: Any) -> str:
    """``sha256:<hex>`` over the canonical JSON of ``obj``."""
    return "sha256:" + hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def to_jsonable(obj: Any) -> Any:
    """Convert to plain JSON-safe Python values (dict/list/str/int/float/bool/None)."""
    return json.loads(canonical_json(obj))


# ─── ids ──────────────────────────────────────────────────────────────────

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_id_lock = threading.Lock()
_last_ms = 0
_last_rand = 0
_RAND_BITS = 30


def _b32(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    """``<prefix>_<16 chars>``: 10 chars of millisecond time + 6 chars of randomness.

    Lexicographically sortable by creation time; strictly increasing within one
    process (the random part is incremented when the millisecond repeats).
    """
    global _last_ms, _last_rand
    with _id_lock:
        now_ms = int(time.time() * 1000)
        if now_ms > _last_ms:
            _last_ms = now_ms
            _last_rand = int.from_bytes(os.urandom(4), "big") & ((1 << _RAND_BITS) - 1)
        else:
            _last_rand += 1
            if _last_rand >= (1 << _RAND_BITS):
                _last_ms += 1
                _last_rand = 0
        ms, rand = _last_ms, _last_rand
    return f"{prefix}_{_b32(ms, 10)}{_b32(rand, 6)}"


# ─── redaction ────────────────────────────────────────────────────────────

REDACTED = "[redacted]"

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "x-api-key",
        "authorization",
        "jwt",
        "jwt_token",
        "raw_token",
        "intent_token",
        "token",
        "access_token",
        "refresh_token",
        "signature",
        "step_proofs",
        "secret",
        "password",
        "session_secret",
        "anthropic_api_key",
        "openai_api_key",
        "groq_api_key",
        "armoriq_api_key",
        "cookie",
        "set-cookie",
        "database_url",
    }
)

_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bgsk_[A-Za-z0-9]{16,}"),
    re.compile(r"\bak_(?:live|test|claw)_[A-Za-z0-9_\-]{4,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"postgres(?:ql)?://[^\s:@/]+:[^\s@/]+@"),
)


def redact_text(text: str) -> str:
    """Mask API keys, JWTs, bearer tokens and DSN passwords inside a string."""
    for pat in _SECRET_VALUE_PATTERNS:
        text = pat.sub(REDACTED, text)
    return text


def redact_secrets(obj: Any) -> Any:
    """Return a JSON-safe copy of ``obj`` with secret-looking keys and values masked."""
    plain = to_jsonable(obj)

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                out[k] = REDACTED if k.lower() in _SECRET_KEYS and v not in (None, "") else walk(v)
            return out
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, str):
            return redact_text(value)
        return value

    return walk(plain)
