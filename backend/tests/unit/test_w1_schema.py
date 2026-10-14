"""W1: JSON-schema subset validator used by the dispatcher (no database)."""

from __future__ import annotations

from rewindsafe.runtime.dispatch import validate_json_schema as v

APPLY = {
    "type": "object",
    "required": ["manifest_id", "manifest_digest", "idempotency_key"],
    "properties": {
        "manifest_id": {"type": "string"},
        "manifest_digest": {"type": "string"},
        "idempotency_key": {"type": "string"},
    },
    "additionalProperties": False,
}
PREPARE = {
    "type": "object",
    "required": ["tenant_id", "repairs"],
    "properties": {
        "tenant_id": {"type": "string"},
        "repairs": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["order_id", "fields"],
                "properties": {
                    "order_id": {"type": "string"},
                    "fields": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["status", "total_cents"]},
                    },
                    "proposed_values": {"type": "object"},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


def test_valid_object_passes():
    assert v(APPLY, {"manifest_id": "m", "manifest_digest": "d", "idempotency_key": "k"}) == []


def test_missing_required_and_unexpected_property_are_reported():
    errs = v(APPLY, {"manifest_id": "m", "extra": 1})
    assert any("manifest_digest" in e and "required" in e for e in errs)
    assert any("idempotency_key" in e for e in errs)
    assert any("extra" in e and "unexpected" in e for e in errs)


def test_wrong_types():
    errs = v(APPLY, {"manifest_id": 5, "manifest_digest": "d", "idempotency_key": "k"})
    assert errs == ["$.manifest_id: expected string, got integer"]
    assert v({"type": "integer"}, True) != []  # bool is not an integer
    assert v({"type": "number"}, 1.5) == [] and v({"type": "number"}, True) != []
    assert v({"type": "integer"}, 1.5) != []
    assert v({"type": "boolean"}, 0) != []
    assert v({"type": ["string", "null"]}, None) == []
    assert v({"type": "object"}, []) != []
    assert v({"type": "array"}, {}) != []


def test_nested_array_items_enum_and_min_items():
    ok = {"tenant_id": "atlas", "repairs": [{"order_id": "O-1", "fields": ["status"]}]}
    assert v(PREPARE, ok) == []
    assert any("at least 1" in e for e in v(PREPARE, {"tenant_id": "atlas", "repairs": []}))
    bad = {"tenant_id": "atlas", "repairs": [{"order_id": "O-1", "fields": ["owner_account"]}]}
    errs = v(PREPARE, bad)
    assert any("repairs[0].fields[0]" in e and "one of" in e for e in errs)
    errs = v(PREPARE, {"tenant_id": "atlas", "repairs": [{"order_id": "O-1", "fields": [], "sql": "x"}]})
    assert any("sql" in e and "unexpected" in e for e in errs)


def test_additional_properties_schema_and_enum_bool_strictness():
    assert v({"type": "object", "additionalProperties": {"type": "integer"}}, {"a": 1}) == []
    assert v({"type": "object", "additionalProperties": {"type": "integer"}}, {"a": "x"}) != []
    assert v({"enum": [1, 2]}, True) != []  # True must not match 1
    assert v({"enum": ["a"]}, "a") == []


def test_minimum_and_min_length_and_unknown_keywords_ignored():
    assert v({"type": "integer", "minimum": 0}, -1) != []
    assert v({"type": "string", "minLength": 2}, "a") != []
    assert v({"type": "string", "pattern": "^x$", "format": "uuid"}, "anything") == []
