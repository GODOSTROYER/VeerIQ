"""Tenant-bound CSV/JSON import and grant creation for generic inventory recovery."""
from __future__ import annotations

import json
import io
from pathlib import Path
from typing import Any, Literal
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field, SecretStr

from rewindsafe.api import auth
from rewindsafe.api.errors import forbidden, not_found
from rewindsafe.config import get_settings
from rewindsafe.contracts import Identity
from rewindsafe.runtime import db, grants
from rewindsafe.workflows.import_recovery import ADAPTER
from rewindsafe.workflows.import_recovery.data import ImportInputError, import_dataset, parse_csv, parse_json, validate_mapping
from rewindsafe.workflows.import_recovery.postgres_source import read_source_table, readonly_connection

router = APIRouter(prefix="/api/imports", tags=["imports"])
SAMPLE_DIR = Path(__file__).resolve().parents[2] / "samples" / "import_recovery"


class ImportBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    current_format: str = Field(pattern="^(csv|json)$")
    current_data: str = Field(max_length=2_000_000)
    snapshot_format: str = Field(pattern="^(csv|json)$")
    snapshot_data: str = Field(max_length=2_000_000)
    authority_format: str = Field(pattern="^(csv|json)$")
    authority_data: str = Field(max_length=2_000_000)
    primary_key: str
    tenant_column: str
    repairable_columns: list[str] = Field(min_length=1, max_length=20)
    repairable_types: dict[str, Literal["string", "integer", "number", "boolean"]] | None = Field(default=None, max_length=20)
    authority_columns: list[str] = Field(default_factory=list, max_length=100)
    authority_mapping: dict[str, str] | None = Field(default=None, max_length=4)
    column_mapping: dict[str, str] = Field(min_length=3, max_length=26)
    approved_snapshot_digest: str = Field(min_length=20, max_length=80)
    snapshot_id: str | None = Field(default=None, max_length=128)


class SampleImportBody(BaseModel):
    pass


class GrantBody(BaseModel):
    dataset_id: str
    record_ids: list[str] = Field(min_length=1, max_length=500)
    repairable_columns: list[str] = Field(min_length=1, max_length=20)


class PostgresImportBody(BaseModel):
    dsn: SecretStr
    display_name: str = Field(min_length=1, max_length=120)
    current_schema: str = "public"
    current_table: str
    snapshot_schema: str = "public"
    snapshot_table: str
    authority_schema: str = "public"
    authority_table: str
    primary_key: str
    tenant_column: str
    repairable_columns: list[str] = Field(min_length=1, max_length=20)
    repairable_types: dict[str, Literal["string", "integer", "number", "boolean"]] | None = Field(default=None, max_length=20)
    authority_columns: list[str] = Field(min_length=4, max_length=100)
    authority_mapping: dict[str, str] | None = Field(default=None, max_length=4)
    column_mapping: dict[str, str] = Field(min_length=3, max_length=26)
    approved_snapshot_digest: str = Field(min_length=20, max_length=80)
    snapshot_id: str | None = Field(default=None, max_length=128)


def _load_sample(sample_id: str) -> dict[str, Any]:
    path = (SAMPLE_DIR / sample_id / "pack.json").resolve()
    if not path.is_relative_to(SAMPLE_DIR.resolve()) or not path.is_file():
        raise not_found("Sample pack not found.")
    metadata = json.loads(path.read_text(encoding="utf-8"))
    folder = path.parent
    current_path = folder / metadata["current_file"]
    authority_path = folder / metadata["authority_file"]
    snapshot_path = folder / metadata["snapshot_file"]
    current_text = current_path.read_text(encoding="utf-8")
    authority_text = authority_path.read_text(encoding="utf-8")
    snapshot_text = snapshot_path.read_text(encoding="utf-8")
    current = parse_csv(current_text) if metadata["current_file"].endswith(".csv") else parse_json(current_text)
    snapshot = parse_json(snapshot_text)
    authority = parse_json(authority_text)
    return {"metadata": metadata, "current": current, "snapshot": snapshot, "authority": authority}


def _persist_import(body: ImportBody, identity: Identity, *, current: list[dict[str, Any]], snapshot: list[dict[str, Any]], authority: list[dict[str, Any]]) -> dict[str, Any]:
    return _persist_import_records(
        display_name=body.display_name, identity=identity, current=current, snapshot=snapshot, authority=authority,
        primary_key=body.primary_key, tenant_column=body.tenant_column, repairable_columns=body.repairable_columns,
        repairable_types=body.repairable_types, authority_columns=body.authority_columns,
        authority_mapping=body.authority_mapping,
        column_mapping=body.column_mapping, approved_snapshot_digest=body.approved_snapshot_digest, snapshot_id=body.snapshot_id,
    )


def _persist_import_records(
    *, display_name: str, identity: Identity, current: list[dict[str, Any]], snapshot: list[dict[str, Any]],
    authority: list[dict[str, Any]], primary_key: str, tenant_column: str, repairable_columns: list[str],
    repairable_types: dict[str, str] | None, authority_columns: list[str], authority_mapping: dict[str, str] | None,
    column_mapping: dict[str, str],
    approved_snapshot_digest: str, snapshot_id: str | None = None,
) -> dict[str, Any]:
    normalized, approved, mapping, snapshot_digest, authority_records, repairable_types = validate_mapping(
        current, snapshot, authority, primary_key=primary_key, tenant_column=tenant_column,
        repairable_columns=repairable_columns, column_mapping=column_mapping,
        authority_columns=authority_columns, repairable_types=repairable_types,
        authority_mapping=authority_mapping,
        approved_snapshot_digest=approved_snapshot_digest,
    )
    authority_mapping = authority_mapping or {flag: flag for flag in ("tombstoned", "revoked", "held", "later_edit")}
    result = import_dataset(display_name=display_name, current_rows=normalized, authority_rows=approved,
        authority_records=authority_records, source_snapshot_rows=snapshot, mapping=mapping, repairable_types=repairable_types,
        authority_mapping=authority_mapping, snapshot_digest=snapshot_digest,
        created_by=identity.identity_id, snapshot_id=snapshot_id)
    by_id = {r["record_id"]: r for r in approved}
    authority_by_id = {r["record_id"]: r for r in authority_records}
    comparisons = []
    for row in normalized:
        snapshot = by_id.get(row["record_id"])
        differing = [f for f in repairable_columns if row["repair_values"].get(f) != snapshot["repair_values"].get(f)]
        flags = authority_by_id.get(row["record_id"], {})
        protected = [flag for flag in ("tombstoned", "revoked", "held", "later_edit") if flags.get(flag)]
        comparisons.append({"record_id": row["record_id"], "tenant_id": row["tenant_id"], "condition": "protected" if protected else "damaged" if differing else "healthy", "protected_reasons": protected, "changed_fields": differing})
    mapped_sources = set(mapping.values())
    preserved_source_columns = sorted({column for row in current for column in row} - mapped_sources)
    mapped_authority_sources = set(authority_mapping.values())
    authority_metadata_columns = sorted(set(authority_columns) - mapped_authority_sources)
    return {**result, "mapping": mapping, "authority_mapping": authority_mapping,
        "preserved_source_columns": preserved_source_columns, "authority_metadata_columns": authority_metadata_columns,
        "repairable_columns": repairable_columns, "repairable_types": repairable_types, "comparisons": comparisons,
        "approved_snapshot_digest": snapshot_digest, "note": "Digest confirms the approved snapshot records; authority records are stored separately and cannot supply repair values."}


@router.get("/samples")
def list_samples(_: Identity = Depends(auth.current_identity)) -> list[dict[str, Any]]:
    samples = []
    for pack in sorted(SAMPLE_DIR.glob("*/pack.json")):
        metadata = json.loads(pack.read_text(encoding="utf-8"))
        samples.append({k: metadata[k] for k in ("sample_id", "display_name", "current_file", "primary_key", "tenant_column", "repairable_columns", "approved_snapshot_digest", "snapshot_id")})
        samples[-1]["repairable_types"] = metadata.get("repairable_types") or {field: {"quantity": "integer", "location": "string"}[field] for field in metadata["repairable_columns"]}
    return samples


@router.get("/samples/{sample_id}")
def get_sample(sample_id: str, _: Identity = Depends(auth.current_identity)) -> dict[str, Any]:
    sample = _load_sample(sample_id)
    meta = sample["metadata"]
    return {"sample_id": meta["sample_id"], "display_name": meta["display_name"], "current_records": sample["current"],
            "snapshot_records": sample["snapshot"], "authority_records": sample["authority"], "primary_key": meta["primary_key"], "tenant_column": meta["tenant_column"],
            "repairable_columns": meta["repairable_columns"], "authority_columns": meta["authority_columns"],
            "authority_mapping": meta.get("authority_mapping") or {flag: flag for flag in ("tombstoned", "revoked", "held", "later_edit")},
            "repairable_types": meta.get("repairable_types") or {field: {"quantity": "integer", "location": "string"}[field] for field in meta["repairable_columns"]},
            "column_mapping": meta["column_mapping"], "snapshot_id": meta["snapshot_id"],
            "approved_snapshot_digest": meta["approved_snapshot_digest"]}


@router.get("/samples/{sample_id}/download")
def download_sample(sample_id: str, _: Identity = Depends(auth.current_identity)) -> Response:
    sample = _load_sample(sample_id)
    meta = sample["metadata"]
    folder = (SAMPLE_DIR / sample_id).resolve()
    files = ["pack.json", "APPROVAL.md", meta["current_file"], meta["snapshot_file"], meta["authority_file"]]
    archive = io.BytesIO()
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zipped:
        for relative in dict.fromkeys(files):
            path = (folder / relative).resolve()
            if not path.is_relative_to(folder) or not path.is_file():
                raise not_found("Sample pack file not found.")
            zipped.write(path, arcname=relative)
    return Response(content=archive.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{sample_id}.zip"'})


@router.post("/preview")
def import_and_preview(body: ImportBody, identity: Identity = Depends(auth.require_operator)) -> dict[str, Any]:
    try:
        current = parse_csv(body.current_data) if body.current_format == "csv" else parse_json(body.current_data)
        snapshot = parse_csv(body.snapshot_data) if body.snapshot_format == "csv" else parse_json(body.snapshot_data)
        authority = parse_csv(body.authority_data) if body.authority_format == "csv" else parse_json(body.authority_data)
        return _persist_import(body, identity, current=current, snapshot=snapshot, authority=authority)
    except ImportInputError as exc:
        from rewindsafe.api.errors import bad_request
        raise bad_request(str(exc), "invalid_import") from exc


@router.post("/postgres-preview")
def import_postgres_preview(body: PostgresImportBody, identity: Identity = Depends(auth.require_operator)) -> dict[str, Any]:
    """Read selected source tables in a bounded read-only transaction; persist only validated copies."""
    try:
        authority_source_columns = list(dict.fromkeys([body.primary_key, body.tenant_column, *body.authority_columns]))
        with readonly_connection(body.dsn.get_secret_value(), get_settings().import_postgres_allowed_hosts) as conn:
            current = read_source_table(conn, body.current_schema, body.current_table)
            snapshot = read_source_table(conn, body.snapshot_schema, body.snapshot_table)
            authority = read_source_table(conn, body.authority_schema, body.authority_table, authority_source_columns)
        return _persist_import_records(
            display_name=body.display_name, identity=identity, current=current, snapshot=snapshot, authority=authority,
            primary_key=body.primary_key, tenant_column=body.tenant_column, repairable_columns=body.repairable_columns,
            repairable_types=body.repairable_types, authority_columns=body.authority_columns, authority_mapping=body.authority_mapping,
            column_mapping=body.column_mapping, approved_snapshot_digest=body.approved_snapshot_digest,
            snapshot_id=body.snapshot_id,
        )
    except ImportInputError as exc:
        from rewindsafe.api.errors import bad_request
        raise bad_request(str(exc), "invalid_import") from exc
    except Exception as exc:
        # Driver errors may include connection strings or server details. Never return or log them.
        from rewindsafe.api.errors import bad_request
        raise bad_request("Read-only PostgreSQL import failed. Check the source settings and allowlisted host.", "postgres_source_failed") from exc


@router.post("/samples/{sample_id}/import")
def import_sample(sample_id: str, _: SampleImportBody, identity: Identity = Depends(auth.require_operator)) -> dict[str, Any]:
    sample = _load_sample(sample_id)
    meta = sample["metadata"]
    current = sample["current"]
    body = ImportBody(display_name=meta["display_name"], current_format="json", current_data=json.dumps(current),
        snapshot_format="json", snapshot_data=json.dumps(sample["snapshot"]), authority_format="json", authority_data=json.dumps(sample["authority"]), primary_key=meta["primary_key"],
        tenant_column=meta["tenant_column"], repairable_columns=meta["repairable_columns"],
        repairable_types=meta.get("repairable_types"),
        authority_columns=meta["authority_columns"], authority_mapping=meta.get("authority_mapping"), column_mapping=meta["column_mapping"],
        approved_snapshot_digest=meta["approved_snapshot_digest"], snapshot_id=meta["snapshot_id"])
    try:
        return _persist_import(body, identity, current=current, snapshot=sample["snapshot"], authority=sample["authority"])
    except ImportInputError as exc:
        from rewindsafe.api.errors import bad_request
        raise bad_request(str(exc), "invalid_import") from exc


@router.post("/grants")
def create_import_grant(body: GrantBody, identity: Identity = Depends(auth.require_operator)) -> dict[str, Any]:
    with db.connection() as conn:
        dataset = conn.execute("SELECT * FROM recovery.import_datasets WHERE dataset_id=%s", (body.dataset_id,)).fetchone()
    if dataset is None or dataset["created_by"] != identity.identity_id:
        raise not_found("Imported dataset not found.")
    current = {r["record_id"]: r for r in dataset["current_rows"]}
    selected = set(body.record_ids)
    if len(selected) != len(body.record_ids) or not selected <= set(current):
        raise forbidden("Select unique records from this imported dataset.")
    if any(current[rid]["tenant_id"] != identity.tenant_id for rid in selected):
        raise forbidden("This grant can include records from your tenant only.", "tenant_mismatch")
    scenarios = {s.scenario_id: s for s in ADAPTER.scenarios()}
    scenario = scenarios.get(body.dataset_id)
    if scenario is None:
        raise not_found("Imported workflow scenario not found.")
    if not body.repairable_columns or len(set(body.repairable_columns)) != len(body.repairable_columns) or not set(body.repairable_columns) <= set(scenario.grant_template["fields"]):
        raise forbidden("Requested fields are outside the imported dataset's repairable field set.")
    scenario = scenario.model_copy(update={"grant_template": {**scenario.grant_template, "record_ids": list(body.record_ids), "fields": list(body.repairable_columns)}})
    grant = grants.create_draft(ADAPTER, scenario, identity)
    return grant.model_dump(mode="json")
