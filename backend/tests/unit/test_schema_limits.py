"""Schema limits: declared maxItems/maxLength/maximum are enforced; tool schemas use no ignored keyword."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from rewindsafe.runtime.dispatch import validate_json_schema as v
from rewindsafe.workflows.import_recovery import ADAPTER as IMPORT_ADAPTER
from rewindsafe.workflows.import_recovery.adapter import MAX_REPAIR_FIELDS
from rewindsafe.workflows.rewindsafe import ADAPTER as ORDER_ADAPTER

# Keywords validate_json_schema enforces. Keep in step with its docstring.
ENFORCED = {
    "type",
    "enum",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
}
# Pure annotations: they never constrain an instance, so ignoring them is correct.
ANNOTATIONS = {"description", "title", "default", "examples"}


def _keywords(schema: Any, where: str = "$") -> Iterator[tuple[str, str]]:
    """Yield (location, keyword) for every keyword in a schema, recursing into subschemas."""
    if not isinstance(schema, dict):
        return
    for key, value in schema.items():
        yield where, key
        if key == "properties" and isinstance(value, dict):
            for name, sub in value.items():
                yield from _keywords(sub, f"{where}.properties.{name}")
        elif key in ("items", "additionalProperties") and isinstance(value, dict):
            yield from _keywords(value, f"{where}.{key}")


def _registered_schemas() -> list[tuple[str, dict[str, Any]]]:
    """(root, input_schema) for every tool the two registered workflow adapters expose."""
    out: list[tuple[str, dict[str, Any]]] = []
    for label, adapter in (("rewindsafe", ORDER_ADAPTER), ("import_recovery", IMPORT_ADAPTER)):
        out.extend((f"{label}.{s.name}", s.input_schema) for s in adapter.tool_specs())
    return out


def test_max_items_at_limit_passes_and_one_over_fails():
    schema = {"type": "array", "maxItems": 2}
    assert v(schema, [1, 2]) == []
    assert v(schema, [1, 2, 3]) == ["$: needs at most 2 item(s)"]


def test_max_items_error_names_nested_path():
    schema = {"type": "object", "properties": {"order_ids": {"type": "array", "maxItems": 2}}}
    assert v(schema, {"order_ids": ["a", "b"]}) == []
    assert v(schema, {"order_ids": ["a", "b", "c"]}) == ["$.order_ids: needs at most 2 item(s)"]


def test_max_length_at_limit_passes_and_one_over_fails():
    schema = {"type": "string", "maxLength": 3}
    assert v(schema, "abc") == []
    assert v(schema, "abcd") == ["$: must be at most 3 character(s)"]
    assert v(schema, "éèà") == []  # counted in characters, not UTF-8 bytes


def test_max_length_error_names_nested_path():
    schema = {"type": "object", "properties": {"reason": {"type": "string", "maxLength": 5}}}
    assert v(schema, {"reason": "short"}) == []
    assert v(schema, {"reason": "too long"}) == ["$.reason: must be at most 5 character(s)"]


def test_maximum_at_limit_passes_and_one_over_fails_and_bool_is_not_a_number():
    schema = {"type": "integer", "maximum": 5}
    assert v(schema, 5) == []
    assert v(schema, 6) == ["$: must be <= 5"]
    assert v({"maximum": 5}, 4.5) == []
    assert v({"maximum": 5}, 5.5) == ["$: must be <= 5"]
    assert v({"maximum": 5}, True) == []  # bool is not compared as a number


def test_declared_order_tool_limits_are_enforced():
    specs = {s.name: s.input_schema for s in ORDER_ADAPTER.tool_specs()}
    ids = [f"O-{i}" for i in range(50)]
    assert v(specs["compare_current"], {"tenant_id": "atlas", "order_ids": ids}) == []
    assert v(specs["compare_current"], {"tenant_id": "atlas", "order_ids": ids + ["O-50"]}) == [
        "$.order_ids: needs at most 50 item(s)"
    ]
    grant = {"tenant_id": "atlas", "grant_id": "g-1"}
    assert v(specs["restore_access_grant"], {**grant, "reason": "x" * 500}) == []
    assert v(specs["restore_access_grant"], {**grant, "reason": "x" * 501}) == [
        "$.reason: must be at most 500 character(s)"
    ]
    assert v(specs["inspect_snapshot"], {"snapshot_id": "s", "tenant_id": "t" * 129}) == [
        "$.tenant_id: must be at most 128 character(s)"
    ]


def test_import_recovery_nested_limits_are_enforced():
    schema = {s.name: s.input_schema for s in IMPORT_ADAPTER.tool_specs()}["prepare_repair_manifest"]
    base = {"tenant_id": "atlas", "snapshot_id": "s-1"}
    ok_row = {"order_id": "O-1", "fields": ["status"] * MAX_REPAIR_FIELDS}
    assert v(schema, {**base, "repairs": [ok_row]}) == []
    over_row = {"order_id": "O-1", "fields": ["status"] * (MAX_REPAIR_FIELDS + 1)}
    assert v(schema, {**base, "repairs": [over_row]}) == [
        f"$.repairs[0].fields: needs at most {MAX_REPAIR_FIELDS} item(s)"
    ]


def test_annotation_keywords_do_not_constrain():
    schema = {"type": "string", "title": "t", "description": "d", "default": "x", "examples": ["y"]}
    assert v(schema, "anything") == []


def test_registered_tool_schemas_use_only_enforced_keywords():
    bad = [
        f"{where} uses '{key}'"
        for root, schema in _registered_schemas()
        for where, key in _keywords(schema, root)
        if key not in ENFORCED | ANNOTATIONS
    ]
    assert bad == [], "validate_json_schema ignores these; enforce the keyword or drop it: " + "; ".join(bad)


def test_guard_walks_the_nested_limits_it_guards():
    seen = {key for root, schema in _registered_schemas() for _, key in _keywords(schema, root)}
    assert {"maxItems", "maxLength", "minItems", "minLength", "items", "properties", "required"} <= seen


def test_guard_flags_a_keyword_the_validator_ignores():
    schema = {"type": "object", "properties": {"ids": {"type": "array", "uniqueItems": True}}}
    flagged = [(where, key) for where, key in _keywords(schema) if key not in ENFORCED | ANNOTATIONS]
    assert flagged == [("$.properties.ids", "uniqueItems")]
