"""Strict CSV/JSON data contract and persistence for imported recovery datasets."""
from __future__ import annotations

import csv
import io
import json
import math
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from rewindsafe.runtime import db
from rewindsafe.runtime.canonical import digest, new_id, to_jsonable, utcnow

MAX_ROWS = 500
MAX_FILE_BYTES = 2_000_000
MAX_CELL_CHARS = 10_000
AUTHORITY_FLAGS = frozenset({"tombstoned", "revoked", "held", "later_edit"})
BASE_COLUMNS = frozenset({"record_id", "tenant_id", "sku", "description", "owner_account", "sync_grant_id"})
SCALAR_TYPES = frozenset({"string", "integer", "number", "boolean"})
LEGACY_TYPES = {"quantity": "integer", "location": "string"}
MAX_REPAIR_FIELDS = 20
MAX_METADATA_COLUMNS = 100
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _valid_source_name(name: Any) -> bool:
    """Source headers may be human-readable; canonical destination names stay strict."""
    return (
        isinstance(name, str)
        and bool(name.strip())
        and name == name.strip()
        and len(name) <= 128
        and not any(unicodedata.category(ch) == "Cc" or ch == "\x00" for ch in name)
    )


class ImportInputError(ValueError):
    pass


def parse_csv(text: str) -> list[dict[str, str]]:
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise ImportInputError("CSV upload exceeds the 2 MB limit.")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = reader.fieldnames or []
        if not headers or len(headers) != len(set(headers)) or any(not _valid_source_name(h) for h in headers):
            raise ImportInputError("CSV headers must be unique, nonempty source column names without control characters.")
        rows = [dict(row) for row in reader]
    except csv.Error as exc:
        raise ImportInputError("CSV could not be parsed.") from exc
    if len(rows) > MAX_ROWS or any(None in row for row in rows):
        raise ImportInputError(f"CSV must contain at most {MAX_ROWS} complete rows.")
    return rows


def parse_json(text: str) -> list[dict[str, Any]]:
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise ImportInputError("JSON upload exceeds the 2 MB limit.")
    try:
        rows = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite number")))
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise ImportInputError("JSON could not be parsed.") from exc
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or any(not isinstance(row, dict) for row in rows):
        raise ImportInputError(f"JSON must be an array of at most {MAX_ROWS} row objects.")
    return rows


def validate_mapping(
    rows: list[dict[str, Any]], snapshot_rows: list[dict[str, Any]], authority_rows: list[dict[str, Any]], *,
    primary_key: str, tenant_column: str, repairable_columns: list[str], column_mapping: dict[str, str],
    authority_columns: list[str] | None = None,
    authority_mapping: dict[str, str] | None = None,
    repairable_types: dict[str, str] | None = None,
    approved_snapshot_digest: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str], str, list[dict[str, Any]], dict[str, str]]:
    if not rows or not snapshot_rows or not authority_rows:
        raise ImportInputError("Current records, approved snapshot records, and authority records are all required.")
    if max(len(rows), len(snapshot_rows), len(authority_rows)) > MAX_ROWS:
        raise ImportInputError(f"Each input must contain at most {MAX_ROWS} rows.")
    if not approved_snapshot_digest or not isinstance(approved_snapshot_digest, str):
        raise ImportInputError("approved_snapshot_digest is required.")
    if digest(snapshot_rows) != approved_snapshot_digest:
        raise ImportInputError("Approved snapshot digest does not match the supplied snapshot records.")
    if not _valid_source_name(primary_key) or not _valid_source_name(tenant_column):
        raise ImportInputError("Primary key and tenant columns must be valid source column names.")
    if primary_key == tenant_column or primary_key not in rows[0] or tenant_column not in rows[0]:
        raise ImportInputError("Primary key and tenant columns must be present and distinct.")
    if not repairable_columns or len(repairable_columns) > MAX_REPAIR_FIELDS or len(repairable_columns) != len(set(repairable_columns)):
        raise ImportInputError(f"Choose between one and {MAX_REPAIR_FIELDS} unique repairable fields.")
    if any(not _IDENT.fullmatch(col) for col in repairable_columns):
        raise ImportInputError("Repairable field names must be simple identifiers.")
    if set(repairable_columns) & (BASE_COLUMNS | {"repair_values"}):
        raise ImportInputError("Primary key, tenant, immutable identity, and executor container fields cannot be repairable.")
    if repairable_types is None:
        if not set(repairable_columns) <= LEGACY_TYPES.keys():
            raise ImportInputError("repairable_types is required for user-selected fields.")
        repairable_types = {field: LEGACY_TYPES[field] for field in repairable_columns}
    if set(repairable_types) != set(repairable_columns) or any(kind not in SCALAR_TYPES for kind in repairable_types.values()):
        raise ImportInputError("Declare exactly one supported scalar type for every repairable field.")
    if column_mapping.get("record_id") != primary_key or column_mapping.get("tenant_id") != tenant_column:
        raise ImportInputError("Column mapping must map record_id and tenant_id to the declared key and tenant columns.")
    if not set(column_mapping) <= BASE_COLUMNS | set(repairable_columns):
        raise ImportInputError("Column mapping contains an undeclared destination field.")
    if any(field not in column_mapping for field in repairable_columns):
        raise ImportInputError("Every repairable field needs a source-column mapping.")
    if len(set(column_mapping.values())) != len(column_mapping):
        raise ImportInputError("Each source column can map to only one destination.")
    repairable_sources = {column_mapping.get(col) for col in repairable_columns}
    if authority_mapping is None:
        authority_mapping = {flag: flag for flag in AUTHORITY_FLAGS}
    if set(authority_mapping) != AUTHORITY_FLAGS or any(not _valid_source_name(source) for source in authority_mapping.values()):
        raise ImportInputError("Map each supported authority flag to one valid source column name.")
    authority_sources = list(authority_mapping.values())
    if len(set(authority_sources)) != len(AUTHORITY_FLAGS):
        raise ImportInputError("Each protected authority flag needs a distinct source column.")
    authority_columns = list(authority_columns) if authority_columns is not None else list(authority_sources)
    if len(authority_columns) != len(set(authority_columns)) or any(not _valid_source_name(col) for col in authority_columns):
        raise ImportInputError("Authority columns must be unique valid source column names.")
    if not set(authority_sources) <= set(authority_columns):
        raise ImportInputError("authority_columns must include every authority flag source column.")
    if len(authority_columns) > MAX_METADATA_COLUMNS:
        raise ImportInputError(f"Authority records may declare at most {MAX_METADATA_COLUMNS} source columns.")
    if set(authority_columns) & {primary_key, tenant_column}:
        raise ImportInputError("Authority columns must be disjoint from the record key and tenant columns.")
    protected_sources = {primary_key, tenant_column, *authority_columns}
    if repairable_sources & protected_sources:
        raise ImportInputError("Primary key, tenant, repairable, and authority columns must be disjoint.")
    required_sources = {primary_key, tenant_column, *(column_mapping[col] for col in repairable_columns)}
    if not required_sources.issubset(rows[0]) or not required_sources.issubset(snapshot_rows[0]):
        raise ImportInputError("Current or snapshot records are missing a declared key, tenant, or repairable field.")
    if not {primary_key, tenant_column, *authority_columns}.issubset(authority_rows[0]):
        raise ImportInputError("Authority records are missing a key, tenant, or declared authority column.")
    current = _normalize_rows(rows, column_mapping, repairable_types)
    snapshot = _normalize_rows(snapshot_rows, column_mapping, repairable_types)
    authority_index = _index_source(authority_rows, primary_key, tenant_column, "authority records")
    cur_by_id = _unique(current, "current records")
    auth_by_id = _unique(snapshot, "approved snapshot records")
    if not cur_by_id.keys() <= auth_by_id.keys():
        raise ImportInputError("Every current record must exist in the approved authority snapshot.")
    if cur_by_id.keys() != authority_index.keys():
        raise ImportInputError("Authority records must cover exactly the current records.")
    if any(cur_by_id[k]["tenant_id"] != auth_by_id[k]["tenant_id"] for k in cur_by_id):
        raise ImportInputError("A record's tenant cannot change between current and approved snapshot data.")
    if any(cur_by_id[k]["tenant_id"] != authority_index[k][tenant_column] for k in cur_by_id):
        raise ImportInputError("A record's tenant cannot change in authority records.")
    allowed_authority_sources = {primary_key, tenant_column, *authority_columns}
    for row in authority_rows:
        unsupported = set(row) - allowed_authority_sources
        if unsupported:
            raise ImportInputError(f"Authority records contain unsupported columns: {', '.join(sorted(unsupported))}.")
        for flag, col in authority_mapping.items():
            if not isinstance(row.get(col), bool):
                raise ImportInputError(f"Authority flag {flag} source {col} must be a boolean on every row.")
        for col in set(authority_columns) - set(authority_sources):
            _validate_metadata_value(row.get(col), f"authority column {col}")
    normalized_authority = [
        {"record_id": row[primary_key], "tenant_id": row[tenant_column],
         **{flag: row[source] for flag, source in authority_mapping.items()},
         "detail": {col: row[col] for col in authority_columns if col not in authority_sources}}
        for row in authority_rows
    ]
    return current, snapshot, dict(column_mapping), approved_snapshot_digest, normalized_authority, dict(repairable_types)


def _index_source(rows: list[dict[str, Any]], key_col: str, tenant_col: str, label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if any(not _valid_source_name(k) or isinstance(v, (dict, list)) or (isinstance(v, str) and len(v) > MAX_CELL_CHARS) for k, v in row.items()):
            raise ImportInputError(f"{label} contain an invalid column or cell value.")
        key = row.get(key_col)
        if not isinstance(key, str) or not key.strip() or not isinstance(row.get(tenant_col), str) or not row[tenant_col].strip():
            raise ImportInputError(f"Every {label} row requires a nonempty key and tenant.")
        if key in indexed:
            raise ImportInputError(f"{label} contain duplicate primary key {key!r}.")
        indexed[key] = row
    return indexed


def _normalize_scalar(value: Any, scalar_type: str, row_number: int, field: str) -> Any:
    if value is None:
        return None
    if scalar_type == "string":
        if not isinstance(value, str) or len(value) > MAX_CELL_CHARS:
            raise ImportInputError(f"Row {row_number} field {field} must be text or null.")
        return value
    if scalar_type == "integer":
        if isinstance(value, bool):
            raise ImportInputError(f"Row {row_number} field {field} must be an integer or null.")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value.strip()):
            return int(value.strip())
        raise ImportInputError(f"Row {row_number} field {field} must be an integer or null.")
    if scalar_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
            raise ImportInputError(f"Row {row_number} field {field} must be a finite number or null.")
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as exc:
            raise ImportInputError(f"Row {row_number} field {field} must be a finite number or null.") from exc
        if not number.is_finite():
            raise ImportInputError(f"Row {row_number} field {field} must be a finite number or null.")
        if number == number.to_integral_value():
            return int(number)
        result = float(number)
        if not math.isfinite(result):
            raise ImportInputError(f"Row {row_number} field {field} exceeds the supported number range.")
        return result
    if scalar_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            return value.strip().lower() == "true"
        raise ImportInputError(f"Row {row_number} field {field} must be true, false, or null.")
    raise ImportInputError(f"Field {field} uses an unsupported scalar type.")


def _validate_metadata_value(value: Any, label: str) -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, Decimal) and value.is_finite():
        return
    if isinstance(value, str) and len(value) <= MAX_CELL_CHARS:
        return
    if isinstance(value, (date, datetime, UUID)):
        return
    raise ImportInputError(f"{label} must be a bounded JSON scalar (string, finite number, boolean, or null).")


def _normalize_rows(rows: list[dict[str, Any]], mapping: dict[str, str], repairable_types: dict[str, str]) -> list[dict[str, Any]]:
    result = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ImportInputError(f"Row {i + 1} must be an object.")
        for source, value in row.items():
            if not _valid_source_name(source):
                raise ImportInputError(f"Row {i + 1} contains an invalid source column name.")
            if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
                raise ImportInputError(f"Row {i + 1} contains an oversized cell.")
            if isinstance(value, (dict, list)):
                raise ImportInputError(f"Row {i + 1} column {source} contains nested data; only flat scalar source columns are supported.")
        missing = set(mapping.values()) - set(row)
        if missing:
            raise ImportInputError(f"Row {i + 1} is missing mapped source columns: {', '.join(sorted(missing))}.")
        mapped = {dest: row[src] for dest, src in mapping.items()}
        for dest in ("record_id", "tenant_id"):
            if not isinstance(mapped.get(dest), str) or not mapped[dest].strip():
                raise ImportInputError(f"Row {i + 1} requires a nonempty {dest} value.")
        for dest in ("sku", "owner_account", "description"):
            if dest in mapped and not isinstance(mapped[dest], str):
                raise ImportInputError(f"Row {i + 1} {dest} must be text.")
        if "owner_account" in mapped and not mapped["owner_account"].strip():
            raise ImportInputError(f"Row {i + 1} owner_account cannot be empty.")
        if "sku" in mapped and not mapped["sku"].strip():
            raise ImportInputError(f"Row {i + 1} sku cannot be empty.")
        normalized = {dest: mapped.get(dest) for dest in BASE_COLUMNS}
        normalized["sku"] = mapped.get("sku") or mapped["record_id"]
        normalized["description"] = mapped.get("description") or ""
        normalized["owner_account"] = mapped.get("owner_account") or "imported"
        normalized["sync_grant_id"] = mapped.get("sync_grant_id")
        normalized["repair_values"] = {
            field: _normalize_scalar(row[mapping[field]], scalar_type, i + 1, field)
            for field, scalar_type in repairable_types.items()
        }
        metadata_columns = [source for source in row if source not in set(mapping.values())]
        if len(metadata_columns) > MAX_METADATA_COLUMNS:
            raise ImportInputError(f"Row {i + 1} has more than {MAX_METADATA_COLUMNS} unmapped source columns.")
        metadata: dict[str, Any] = {}
        for source in metadata_columns:
            _validate_metadata_value(row[source], f"row {i + 1} source column {source}")
            metadata[source] = row[source]
        normalized["source_metadata"] = metadata
        # Keep read-only compatibility mirrors for existing consumers. New
        # execution reads/writes only repair_values; the database trigger keeps
        # legacy quantity/location columns synchronized when types match.
        normalized["quantity"] = normalized["repair_values"].get("quantity", 0)
        if not isinstance(normalized["quantity"], int) or isinstance(normalized["quantity"], bool):
            normalized["quantity"] = 0
        normalized["location"] = normalized["repair_values"].get("location")
        if normalized["location"] is not None and not isinstance(normalized["location"], str):
            normalized["location"] = None
        result.append(normalized)
    return result


def _unique(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    indexed = {}
    for row in rows:
        key = row["record_id"]
        if key in indexed:
            raise ImportInputError(f"{label} contain duplicate primary key {key!r}.")
        indexed[key] = row
    return indexed


def restore_values_from_source(
    source_records: list[dict[str, Any]], column_mapping: dict[str, str], repairable_types: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Re-derive each record's repair values from digest-covered source records, using the import rules.

    The snapshot's stored ``rows`` copy is not covered by its digest, so apply checks against this instead.
    """
    derived: dict[str, dict[str, Any]] = {}
    for row in _normalize_rows(source_records, column_mapping, repairable_types):
        if row["record_id"] in derived:
            raise ImportInputError("Approved snapshot records contain a duplicate primary key.")
        derived[row["record_id"]] = row["repair_values"]
    return derived


def import_dataset(
    *, display_name: str, current_rows: list[dict[str, Any]], authority_rows: list[dict[str, Any]], authority_records: list[dict[str, Any]],
    mapping: dict[str, str], repairable_types: dict[str, str], snapshot_digest: str, created_by: str, snapshot_id: str | None = None,
    authority_mapping: dict[str, str] | None = None,
    source_snapshot_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist validated data. Application rows and authority snapshots have separate tables."""
    dataset_id = new_id("imp")
    snapshot_id = snapshot_id or new_id("snap")
    tenants = {row["tenant_id"] for row in current_rows}
    if len(tenants) == 1:
        tenant_hint = next(iter(tenants))
    else:
        tenant_hint = "multi"
    source_snapshot_rows = source_snapshot_rows if source_snapshot_rows is not None else authority_rows
    if digest(source_snapshot_rows) != snapshot_digest:
        raise ImportInputError("Approved snapshot digest does not match the supplied snapshot records.")
    snapshot_body = {"rows": authority_rows, "source_records": source_snapshot_rows, "mapping": mapping}
    authority_mapping = authority_mapping or {flag: flag for flag in AUTHORITY_FLAGS}
    with db.transaction() as conn:
        if conn.execute("SELECT 1 FROM recovery.import_snapshots WHERE snapshot_id=%s", (snapshot_id,)).fetchone():
            snapshot_id = f"{snapshot_id}-{new_id('copy').split('_', 1)[-1]}"
        conn.execute(
            "INSERT INTO recovery.import_snapshots(snapshot_id,sample_id,tenant_id,content,content_digest,approved,approved_by,approved_at) VALUES (%s,%s,%s,%s,%s,true,%s,now())",
            (snapshot_id, dataset_id, tenant_hint, Jsonb(to_jsonable(snapshot_body)), snapshot_digest, created_by),
        )
        conn.execute(
            "INSERT INTO recovery.import_datasets(dataset_id,display_name,tenant_id,snapshot_id,snapshot_digest,mapping,current_rows,authority_records,repairable_types,authority_mapping,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (dataset_id, display_name[:120], tenant_hint, snapshot_id, snapshot_digest, Jsonb(mapping), Jsonb(to_jsonable(current_rows)), Jsonb(to_jsonable(authority_records)), Jsonb(repairable_types), Jsonb(authority_mapping), created_by),
        )
        for field_name, scalar_type in repairable_types.items():
            conn.execute(
                "INSERT INTO recovery.import_dataset_fields(dataset_id,field_name,source_column,scalar_type) VALUES (%s,%s,%s,%s)",
                (dataset_id, field_name, mapping[field_name], scalar_type),
            )
        for state in authority_records:
            conn.execute(
                "INSERT INTO recovery.import_authority_state(dataset_id,record_id,tenant_id,tombstoned,revoked,held,later_edit,detail) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (dataset_id, state["record_id"], state["tenant_id"], state["tombstoned"], state["revoked"], state["held"], state["later_edit"], Jsonb(state["detail"])),
            )
        for row in current_rows:
            conn.execute(
                "INSERT INTO app.import_inventory_items(dataset_id,record_id,tenant_id,sku,description,quantity,location,owner_account,sync_grant_id,repair_values,source_metadata,row_version,updated_at,updated_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,2,now(),%s)",
                (dataset_id, row["record_id"], row["tenant_id"], row["sku"], row.get("description", ""),
                 row.get("quantity", 0), row.get("location"),
                 row.get("owner_account", "imported"), row.get("sync_grant_id"), Jsonb(to_jsonable(row["repair_values"])), Jsonb(to_jsonable(row["source_metadata"])), "imported_current"),
            )
    return {"dataset_id": dataset_id, "snapshot_id": snapshot_id, "snapshot_digest": snapshot_digest,
            "tenant_ids": sorted(tenants), "record_count": len(current_rows)}
