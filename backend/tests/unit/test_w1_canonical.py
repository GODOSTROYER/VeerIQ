"""W1: canonical JSON, digests, ids, redaction (no database)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

import pytest
from pydantic import BaseModel

from rewindsafe.contracts import Layer, Outcome
from rewindsafe.runtime.canonical import (
    canonical_json,
    digest,
    new_id,
    redact_secrets,
    redact_text,
    to_jsonable,
    utcnow,
)


class Color(Enum):
    RED = "red"
    BLUE = "blue"


class Item(BaseModel):
    name: str
    when: datetime
    price: Decimal
    layer: Layer


def test_key_order_does_not_change_digest():
    assert digest({"a": 1, "b": [1, 2, {"x": 1, "y": 2}]}) == digest({"b": [1, 2, {"y": 2, "x": 1}], "a": 1})


def test_canonical_json_is_compact_sorted_and_keeps_unicode():
    assert canonical_json({"b": 1, "a": "café"}) == '{"a":"café","b":1}'


def test_digest_format_and_sensitivity():
    d = digest({"a": 1})
    assert d.startswith("sha256:") and len(d) == len("sha256:") + 64
    assert d != digest({"a": 2})
    assert d == digest({"a": 1})


def test_datetime_is_iso_utc_z_regardless_of_zone():
    utc = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
    ist = utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    naive = datetime(2026, 10, 5, 0, 0)
    assert canonical_json(utc) == '"2026-10-05T00:00:00Z"'
    assert canonical_json(ist) == canonical_json(utc)
    assert canonical_json(naive) == canonical_json(utc)  # naive is treated as UTC


def test_decimal_and_enum_and_set_and_bytes():
    assert canonical_json({"p": Decimal("12.50")}) == '{"p":"12.50"}'
    assert canonical_json({"c": Color.RED, Color.BLUE: 1}) == '{"blue":1,"c":"red"}'
    assert canonical_json({"s": {3, 1, 2}}) == '{"s":[1,2,3]}'
    assert canonical_json(b"\x01\xff") == '"01ff"'


def test_base_model_uses_json_dump_and_enums_by_value():
    item = Item(
        name="x", when=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), price=Decimal("1.5"), layer=Layer.GRANT
    )
    data = json.loads(canonical_json(item))
    assert data["layer"] == "grant" and data["when"].startswith("2026-01-02T03:04:05")
    assert digest(item) == digest(item.model_copy())
    assert to_jsonable([item])[0]["name"] == "x"


def test_nan_and_unknown_types_are_rejected():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
    with pytest.raises(TypeError):
        canonical_json({"x": object()})


def test_bool_is_not_confused_with_int():
    assert canonical_json([True, 1]) == "[true,1]"


def test_new_id_shape_uniqueness_and_ordering():
    ids = [new_id("run") for _ in range(2000)]
    assert len(set(ids)) == 2000
    assert all(i.startswith("run_") and len(i) == len("run_") + 16 for i in ids)
    assert ids == sorted(ids)  # strictly sortable within a process


def test_utcnow_is_aware():
    assert utcnow().tzinfo is not None


def test_redact_text_masks_keys_jwts_bearer_and_dsn_passwords():
    jwt = "eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJl"
    text = f"key ak_live_ABCDEF123456 jwt {jwt} Bearer abcdefghijklmnop1234 postgresql://u:pw@host/db"
    out = redact_text(text)
    assert "ak_live_ABCDEF123456" not in out and jwt not in out and "abcdefghijklmnop1234" not in out
    assert ":pw@" not in out


def test_redact_secrets_masks_secret_keys_recursively_but_keeps_ids():
    obj = {
        "token_id": "intent_123",
        "jwt_token": "eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2ln",
        "nested": [{"api_key": "ak_test_zzzzzzzz", "keep": 1}],
        "step_proofs": [{"a": 1}],
        "note": "used ak_claw_secretsecret",
        "outcome": Outcome.ALLOW,
    }
    out = redact_secrets(obj)
    dumped = json.dumps(out)
    assert out["token_id"] == "intent_123"
    assert out["jwt_token"] == "[redacted]" and out["step_proofs"] == "[redacted]"
    assert out["nested"][0] == {"api_key": "[redacted]", "keep": 1}
    assert "ak_claw_secretsecret" not in dumped and out["outcome"] == "allow"
