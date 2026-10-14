"""Declarative CSV/JSON inventory recovery adapter on the shared dispatcher."""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from psycopg.types.json import Jsonb

from rewindsafe.contracts import (
    ApprovalRecord, DecisionSource, DispatchStatus, ExecutionManifest, ExecutionReceipt,
    GrantLimits, Identity, InvariantCheck, InvariantStatus, Layer, ManifestChange,
    ManifestPreconditions, Outcome, ReceiptChange, ScenarioSpec, TaskGrant, ToolKind, ToolSpec,
)
from rewindsafe.runtime import db
from rewindsafe.runtime.canonical import digest, new_id, to_jsonable, utcnow
from rewindsafe.runtime.adapter import AdmissionResult, ToolContext, ToolExecution, make_decision
from rewindsafe.workflows.import_recovery.data import ImportInputError, restore_values_from_source

WORKFLOW_ID = "rewindsafe.import_recovery"
# Reuse the already registered ArmorIQ MCP policy: these tools deliberately
# have the same names/contracts as the order-repair workflow.
MCP_NAME = "rewindsafe-recovery"
TOOLS = ("inspect_snapshot", "compare_current", "prepare_repair_manifest", "apply_repair_manifest", "get_recovery_receipt")
MAX_REPAIR_FIELDS = 20
GRANT_TTL = timedelta(minutes=30)


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _id() -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": 128}


def _tools() -> list[ToolSpec]:
    return [
        ToolSpec(name="inspect_snapshot", title="Inspect approved snapshot", description="Read the approved inventory values for records in this task.", kind=ToolKind.READ,
                 input_schema=_schema({"snapshot_id": _id(), "tenant_id": _id(), "order_ids": {"type": "array", "items": _id(), "maxItems": 500}}, ["snapshot_id", "tenant_id"])),
        ToolSpec(name="compare_current", title="Compare current inventory", description="Compare current inventory records with the approved snapshot and report protected records.", kind=ToolKind.READ,
                 input_schema=_schema({"tenant_id": _id(), "order_ids": {"type": "array", "items": _id(), "maxItems": 500}}, ["tenant_id", "order_ids"])),
        ToolSpec(name="prepare_repair_manifest", title="Prepare inventory repair", description="Prepare exact changes whose restored values are resolved from the approved snapshot. This does not write inventory data.", kind=ToolKind.PREPARE,
                 input_schema=_schema({"tenant_id": _id(), "snapshot_id": _id(), "repairs": {"type": "array", "minItems": 1, "maxItems": 500,
                     "items": _schema({"order_id": _id(), "fields": {"type": "array", "minItems": 1, "items": _id(), "maxItems": MAX_REPAIR_FIELDS}, "proposed_values": {"type": "object"}}, ["order_id", "fields"])}}, ["tenant_id", "snapshot_id", "repairs"])),
        ToolSpec(name="apply_repair_manifest", title="Apply inventory repair", description="Apply a previously approved manifest with a digest and idempotency key. Current tenant, row version, tombstone, hold, revocation and snapshot conditions are checked in the transaction.", kind=ToolKind.MUTATE, mutator=True,
                 input_schema=_schema({"manifest_id": _id(), "manifest_digest": {"type": "string", "minLength": 8, "maxLength": 128}, "idempotency_key": _id()}, ["manifest_id", "manifest_digest", "idempotency_key"])),
        ToolSpec(name="get_recovery_receipt", title="Get inventory receipt", description="Read the receipt for this task's committed repair.", kind=ToolKind.READ,
                 input_schema=_schema({"operation_id": _id(), "manifest_id": _id()}, [])),
    ]


def _dataset(conn: Any, dataset_id: str) -> dict[str, Any] | None:
    return conn.execute("SELECT * FROM recovery.import_datasets WHERE dataset_id=%s", (dataset_id,)).fetchone()


def _field_catalog(conn: Any, dataset_id: str) -> dict[str, str]:
    return {row["field_name"]: row["scalar_type"] for row in conn.execute(
        "SELECT field_name,scalar_type FROM recovery.import_dataset_fields WHERE dataset_id=%s ORDER BY field_name",
        (dataset_id,),
    ).fetchall()}


def _values_match(values: Any, catalog: dict[str, str]) -> bool:
    if not isinstance(values, dict) or set(values) != set(catalog):
        return False
    for field, kind in catalog.items():
        value = values[field]
        if value is None:
            continue
        if kind == "string" and isinstance(value, str):
            continue
        if kind == "integer" and type(value) is int:
            continue
        if kind == "number" and type(value) in (int, float) and math.isfinite(value):
            continue
        if kind == "boolean" and type(value) is bool:
            continue
        return False
    return True


def _same_value(left: Any, right: Any) -> bool:
    """Exact match. Python treats True, 1 and 1.0 as equal, so the type must match as well."""
    return type(left) is type(right) and left == right


class ImportRecoveryAdapter:
    workflow_id = WORKFLOW_ID
    mcp_name = MCP_NAME

    def tool_specs(self) -> list[ToolSpec]:
        return _tools()

    def scenarios(self) -> list[ScenarioSpec]:
        try:
            with db.connection() as conn:
                rows = conn.execute("SELECT dataset_id,display_name,tenant_id,snapshot_id,current_rows FROM recovery.import_datasets ORDER BY created_at DESC").fetchall()
                for row in rows:
                    row["repairable_types"] = _field_catalog(conn, row["dataset_id"])
        except Exception:
            return []
        scenarios = []
        for row in rows:
            if not row["repairable_types"]:
                continue
            i = len(scenarios)
            ids = [r["record_id"] for r in row["current_rows"]]
            scenarios.append(ScenarioSpec(
                scenario_id=row["dataset_id"], workflow=WORKFLOW_ID, title=f"{row['display_name']} inventory recovery",
                tagline="Restore repairable inventory fields from an approved snapshot.",
                description="Inspect and compare the imported current records, prepare a snapshot-derived manifest, and apply only the fields authorized in the task grant.",
                kind="baseline", order=i + 1, default_planner="scripted",
                grant_template={"dataset_id": row["dataset_id"], "resources": {"order": ids}, "fields": sorted(row["repairable_types"]), "limits": {"max_commits": 1}},
                expected_outcome="Only eligible records within one tenant are repaired; later changes and protected records remain untouched.",
                highlights=["Values come from the digest-bound approved snapshot", "Tenant and row versions are checked again at apply time", "A dataset catalog and a column-limited database role restrict repair values"],
            ))
        return scenarios

    def build_grant(self, scenario: ScenarioSpec, identity: Identity, fixture_generation: int) -> TaskGrant:
        template = scenario.grant_template
        with db.connection() as conn:
            data = _dataset(conn, template["dataset_id"])
            catalog = _field_catalog(conn, template["dataset_id"])
        if data is None:
            raise ValueError("Imported dataset is unavailable.")
        now = utcnow()
        tenant = identity.tenant_id
        ids = list(template.get("record_ids") or [r["record_id"] for r in data["current_rows"] if r["tenant_id"] == tenant])
        current_ids = {r["record_id"] for r in data["current_rows"] if r["tenant_id"] == tenant}
        if not ids or len(ids) != len(set(ids)) or not set(ids) <= current_ids:
            raise ValueError("The grant must name existing records from the operator's tenant.")
        fields = list(template.get("fields", []))
        if not fields or len(fields) > MAX_REPAIR_FIELDS or len(fields) != len(set(fields)) or not set(fields) <= set(catalog):
            raise ValueError("The grant fields must be a unique nonempty subset of this dataset's repair catalog.")
        grant = TaskGrant(
            grant_id=new_id("grt"), workflow=WORKFLOW_ID, scenario_id=scenario.scenario_id,
            principal=identity.identity_id, principal_email=identity.email, tenant_id=tenant,
            incident_id=None, purpose=f"Recover selected inventory records for tenant {tenant} from approved snapshot {data['snapshot_id']}.",
            # The shared scripted planner and outcome summarizer consume the `order` resource key.
            # Inventory remains in its own table and is updated by its own constrained executor role.
            allowed_tools=list(TOOLS), resources={"order": ids, "snapshot": [data["snapshot_id"]]},
            fields=fields, prohibited_effects=["Change record identity, tenant, SKU, owner or access grants", "Restore tombstoned records", "Overwrite later changes", "Touch another tenant"],
            source_constraints={"dataset_id": data["dataset_id"], "snapshot_id": data["snapshot_id"], "snapshot_digest": data["snapshot_digest"]},
            limits=GrantLimits(**template.get("limits", {})), created_at=now, expires_at=now + GRANT_TTL,
            fixture_generation=fixture_generation, grant_digest="sha256:pending",
        )
        return grant.model_copy(update={"grant_digest": digest(grant.model_dump(mode="json", exclude={"grant_digest", "status", "commits_used", "authorized_at", "authorized_by"}))})

    def plan_tool_calls(self, grant: TaskGrant) -> list[dict[str, Any]]:
        ids = sorted(grant.resources["order"])
        snap = grant.source_constraints["snapshot_id"]
        return [
            {"name": "inspect_snapshot", "args": {"snapshot_id": snap, "tenant_id": grant.tenant_id, "order_ids": ids}},
            {"name": "compare_current", "args": {"tenant_id": grant.tenant_id, "order_ids": ids}},
            {"name": "prepare_repair_manifest", "args": {"tenant_id": grant.tenant_id, "snapshot_id": snap, "repairs": [{"order_id": x, "fields": grant.fields} for x in ids]}},
            {"name": "apply_repair_manifest", "args": {"manifest_id": "<prepared manifest>", "manifest_digest": "<manifest digest>", "idempotency_key": "<run idempotency key>"}},
            {"name": "get_recovery_receipt", "args": {}},
        ]

    def canonicalize(self, ctx: ToolContext, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        out = dict(args)
        if "tenant_id" in out:
            out["tenant_id"] = str(out["tenant_id"]).strip()
        if "order_ids" in out:
            out["order_ids"] = sorted(set(out["order_ids"]))
        if tool == "prepare_repair_manifest":
            out["repairs"] = sorted(out["repairs"], key=lambda r: str(r.get("order_id", "")))
            for repair in out["repairs"]:
                repair["fields"] = sorted(set(repair.get("fields", [])))
                repair.pop("proposed_values", None)
        if tool == "apply_repair_manifest":
            with db.connection() as conn:
                row = conn.execute("SELECT body FROM runtime.manifests WHERE manifest_id=%s AND grant_id=%s", (args.get("manifest_id"), ctx.grant.grant_id)).fetchone()
            manifest = ExecutionManifest.model_validate(row["body"]) if row else None
            out = {"manifest_id": args.get("manifest_id"), "manifest_digest": args.get("manifest_digest"),
                   "tenant_id": ctx.grant.tenant_id,
                   "order_ids": sorted({c.row_id for c in manifest.changes}) if manifest else [],
                   # Inventory restores have no monetary value; the shared sponsor contract requires a numeric amount.
                   "amount": 0.0}
        return out

    def check_grant(self, ctx: ToolContext, tool: str, args: dict[str, Any]) -> AdmissionResult:
        tenant = args.get("tenant_id")
        requested = list(args.get("order_ids", []))
        if tool == "prepare_repair_manifest":
            requested = [r.get("order_id") for r in args.get("repairs", [])]
            repair_ids = [r.get("order_id") for r in args.get("repairs", [])]
            if len(repair_ids) != len(set(repair_ids)):
                return self._block(ctx, "duplicate_record", "A record may appear only once in a repair manifest.")
            if any(len(r.get("fields", [])) != len(set(r.get("fields", []))) for r in args.get("repairs", [])):
                return self._block(ctx, "duplicate_field", "A repair field may appear only once per record.")
        elif len(requested) != len(set(requested)):
            return self._block(ctx, "duplicate_record", "A record may appear only once in a request.")
        if tenant is not None and tenant != ctx.grant.tenant_id:
            return self._block(ctx, "tenant_scope", "Requested tenant is outside this task grant.")
        if requested and not set(requested) <= set(ctx.grant.resources.get("order", [])):
            return self._block(ctx, "resource_scope", "A requested record is outside this task grant.")
        with db.connection() as conn:
            catalog = _field_catalog(conn, ctx.grant.source_constraints["dataset_id"])
        for repair in args.get("repairs", []):
            if not set(repair.get("fields", [])) <= set(ctx.grant.fields) or not set(repair.get("fields", [])) <= set(catalog):
                return self._block(ctx, "field_scope", "A requested field is outside this task grant.")
        if args.get("snapshot_id") and args["snapshot_id"] != ctx.grant.source_constraints.get("snapshot_id"):
            return self._block(ctx, "snapshot_scope", "This task grant names another approved snapshot.")
        return AdmissionResult()

    def validate(self, ctx: ToolContext, tool: str, args: dict[str, Any]) -> AdmissionResult:
        return AdmissionResult()

    def execute(self, ctx: ToolContext, tool: str, args: dict[str, Any]) -> ToolExecution:
        if tool == "inspect_snapshot":
            with db.connection() as conn:
                dataset = _dataset(conn, ctx.grant.source_constraints["dataset_id"])
                snap = conn.execute("SELECT * FROM recovery.import_snapshots WHERE snapshot_id=%s", (args["snapshot_id"],)).fetchone()
            if not dataset or not snap or not self._snapshot_ok(snap, ctx.grant.source_constraints["snapshot_digest"]):
                return self._blocked_exec(ctx, "snapshot_digest", "Approved snapshot is missing or its digest changed.")
            allowed = set(ctx.grant.resources["order"])
            # Source metadata may contain arbitrary business text. Keep it stored
            # immutably for provenance, but never feed it to the planner.
            rows = [
                {"record_id": r["record_id"], "tenant_id": r["tenant_id"], "repair_values": r["repair_values"]}
                for r in snap["content"]["rows"]
                if r["record_id"] in allowed and r["tenant_id"] == ctx.grant.tenant_id
            ]
            return ToolExecution(status=DispatchStatus.EXECUTED, observation={"snapshot_id": snap["snapshot_id"], "snapshot_digest": snap["content_digest"], "rows": rows}, summary=f"Read {len(rows)} approved inventory record(s).")
        if tool == "compare_current":
            return self._compare(ctx, args)
        if tool == "prepare_repair_manifest":
            return self._prepare(ctx, args)
        if tool == "apply_repair_manifest":
            return self._apply(ctx, args)
        if tool == "get_recovery_receipt":
            return self._receipt(ctx, args)
        return ToolExecution(status=DispatchStatus.FAILED, summary=f"Unknown import recovery tool {tool}.")

    def _compare(self, ctx: ToolContext, args: dict[str, Any]) -> ToolExecution:
        ids = args["order_ids"]
        with db.connection() as conn:
            data = _dataset(conn, ctx.grant.source_constraints["dataset_id"])
            rows = conn.execute("SELECT * FROM app.import_inventory_items WHERE dataset_id=%s AND record_id = ANY(%s) AND tenant_id=%s ORDER BY record_id", (ctx.grant.source_constraints["dataset_id"], ids, ctx.grant.tenant_id)).fetchall()
            snapshot = conn.execute("SELECT * FROM recovery.import_snapshots WHERE snapshot_id=%s", (ctx.grant.source_constraints["snapshot_id"],)).fetchone()
            catalog = _field_catalog(conn, ctx.grant.source_constraints["dataset_id"])
            guards = self._guards(conn, ctx.grant.source_constraints["dataset_id"], ids)
            revokes = self._revoked(conn, rows)
        if not data or not snapshot or not self._snapshot_ok(snapshot, ctx.grant.source_constraints["snapshot_digest"]):
            return self._blocked_exec(ctx, "snapshot_digest", "Approved snapshot is unavailable.")
        before = {r["record_id"]: r for r in snapshot["content"]["rows"]}
        if not catalog or not set(ctx.grant.fields) <= set(catalog) or any(not _values_match(r.get("repair_values"), catalog) for r in rows):
            return self._blocked_exec(ctx, "field_catalog", "Current inventory values do not match the dataset field catalog.")
        if any(not _values_match(r.get("repair_values"), catalog) for r in before.values()):
            return self._blocked_exec(ctx, "snapshot_value", "Approved snapshot values do not match the dataset field catalog.")
        repair_fields = list(ctx.grant.fields)
        output = []
        for row in rows:
            rid = row["record_id"]
            protected = self._protect_reason(rid, guards, revokes)
            if protected is None and int(row["row_version"]) > 2:
                protected = "later_edit"
            current_values = row["repair_values"]
            snapshot_values = before[rid]["repair_values"]
            changes = [f for f in repair_fields if current_values.get(f) != snapshot_values.get(f)]
            condition = "deleted_tombstoned" if protected == "tombstoned" else "on_hold" if protected == "held" else "changed_after_snapshot" if protected in {"revoked", "later_edit"} else ("damaged" if changes else "healthy")
            output.append({"order_id": rid, "tenant_id": row["tenant_id"], "condition": condition, "protected_reason": protected, "changed_fields": changes, "differing_fields": changes, "current": {f: current_values.get(f) for f in repair_fields}, "snapshot": {f: snapshot_values.get(f) for f in repair_fields}, "row_version": row["row_version"]})
        return ToolExecution(status=DispatchStatus.EXECUTED, observation={"orders": output}, summary=f"Compared {len(output)} inventory record(s).")

    def _prepare(self, ctx: ToolContext, args: dict[str, Any]) -> ToolExecution:
        dataset_id = ctx.grant.source_constraints["dataset_id"]
        with db.transaction() as conn:
            catalog = _field_catalog(conn, dataset_id)
            if not catalog or not set(ctx.grant.fields) <= set(catalog):
                return self._blocked_exec(ctx, "field_catalog", "The repair field catalog is missing or changed.")
            snap = conn.execute("SELECT * FROM recovery.import_snapshots WHERE snapshot_id=%s AND approved", (args["snapshot_id"],)).fetchone()
            if not snap or not self._snapshot_ok(snap, ctx.grant.source_constraints["snapshot_digest"]):
                return self._blocked_exec(ctx, "snapshot_digest", "Approved snapshot is missing or changed.")
            snapshot = {r["record_id"]: r for r in snap["content"]["rows"]}
            target_ids = [r["order_id"] for r in args["repairs"]]
            rows = conn.execute("SELECT * FROM app.import_inventory_items WHERE dataset_id=%s AND record_id=ANY(%s) AND tenant_id=%s ORDER BY record_id", (dataset_id, target_ids, ctx.grant.tenant_id)).fetchall()
            by_id = {r["record_id"]: r for r in rows}
            if any(not _values_match(r.get("repair_values"), catalog) for r in rows) or any(not _values_match(r.get("repair_values"), catalog) for r in snapshot.values()):
                return self._blocked_exec(ctx, "field_catalog", "Current or snapshot values do not match the dataset field catalog.")
            guards = self._guards(conn, dataset_id, target_ids)
            revokes = self._revoked(conn, rows)
            changes = []
            versions = {}
            safe_ids = []
            for req in args["repairs"]:
                rid = req["order_id"]
                row, source = by_id.get(rid), snapshot.get(rid)
                if not row or not source or row["tenant_id"] != ctx.grant.tenant_id or source["tenant_id"] != ctx.grant.tenant_id:
                    continue
                if self._protect_reason(rid, guards, revokes):
                    continue
                if int(row["row_version"]) > 2:
                    continue
                versions[rid] = int(row["row_version"])
                safe_ids.append(rid)
                for field in req["fields"]:
                    if field not in ctx.grant.fields or field not in catalog:
                        continue
                    new = source["repair_values"].get(field)
                    current_value = row["repair_values"].get(field)
                    if current_value != new:
                        changes.append(ManifestChange(entity="inventory_item", row_id=rid, field=field, current_value=current_value, new_value=new, source_path=f"snapshot:{snap['snapshot_id']}/inventory/{rid}/{field}"))
            if not changes:
                return self._blocked_exec(ctx, "nothing_to_repair", "Nothing to repair: no eligible record differs from the approved snapshot in the requested fields. No manifest was prepared.")
            manifest = ExecutionManifest(
                manifest_id=new_id("man"), grant_id=ctx.grant.grant_id, run_id=ctx.run_id,
                principal=ctx.grant.principal, tenant_id=ctx.grant.tenant_id, workflow=WORKFLOW_ID,
                snapshot_id=snap["snapshot_id"], snapshot_digest=snap["content_digest"], changes=changes,
                preconditions=ManifestPreconditions(authority_epoch=0, row_versions=versions,
                    fixture_generation=ctx.grant.fixture_generation, tombstone_free=safe_ids, hold_free=safe_ids),
                requires_review=False, content_digest="sha256:pending", created_at=utcnow(),
            )
            manifest = manifest.model_copy(update={"content_digest": digest(manifest.model_dump(mode="json", exclude={"status", "created_at", "content_digest"}))})
            conn.execute("INSERT INTO runtime.manifests(manifest_id,grant_id,run_id,tenant_id,body,content_digest,status,fixture_generation,created_at) VALUES (%s,%s,%s,%s,%s,%s,'prepared',%s,%s)",
                (manifest.manifest_id, manifest.grant_id, manifest.run_id, manifest.tenant_id, Jsonb(to_jsonable(manifest)), manifest.content_digest, manifest.preconditions.fixture_generation, manifest.created_at))
        return ToolExecution(status=DispatchStatus.EXECUTED, observation={"manifest_id": manifest.manifest_id, "manifest_digest": manifest.content_digest,
            "changes": [c.model_dump(mode="json") for c in changes], "requires_review": False}, summary=f"Prepared {len(changes)} exact inventory field change(s).", manifest=manifest)

    def _apply(self, ctx: ToolContext, args: dict[str, Any]) -> ToolExecution:
        operation_id = new_id("op")
        try:
            with db.transaction() as conn:
                prior = conn.execute("SELECT * FROM runtime.receipts WHERE grant_id=%s AND idempotency_key=%s FOR UPDATE", (ctx.grant.grant_id, args["idempotency_key"])).fetchone()
                if prior:
                    if prior["manifest_digest"] == args["manifest_digest"]:
                        receipt = ExecutionReceipt.model_validate(prior["body"])
                        return ToolExecution(status=DispatchStatus.DUPLICATE, observation={"status": "duplicate", "operation_id": receipt.operation_id, "receipt": to_jsonable(receipt)}, summary="This idempotency key already committed; returned its receipt.", receipt=receipt)
                    return self._blocked_exec(ctx, "idempotency_conflict", "This idempotency key was already used for another payload.")
                grantrow = conn.execute("SELECT status,commits_used,max_commits,expires_at,tenant_id,fixture_generation FROM runtime.task_grants WHERE grant_id=%s FOR UPDATE", (ctx.grant.grant_id,)).fetchone()
                mr = conn.execute("SELECT body,status FROM runtime.manifests WHERE manifest_id=%s AND grant_id=%s FOR UPDATE", (args["manifest_id"], ctx.grant.grant_id)).fetchone()
                if not grantrow or grantrow["status"] != "active" or grantrow["expires_at"] <= utcnow() or grantrow["commits_used"] >= grantrow["max_commits"]:
                    return self._blocked_exec(ctx, "grant_inactive", "Grant is no longer active or has no commits remaining.")
                if not mr or mr["status"] != "prepared":
                    return self._blocked_exec(ctx, "manifest_digest", "Manifest is not prepared.")
                manifest = ExecutionManifest.model_validate(mr["body"])
                if manifest.content_digest != args["manifest_digest"] or args["manifest_digest"] != digest(manifest.model_dump(mode="json", exclude={"status", "created_at", "content_digest"})):
                    return self._blocked_exec(ctx, "manifest_digest", "Manifest digest is invalid.")
                if (manifest.grant_id != ctx.grant.grant_id or manifest.tenant_id != ctx.grant.tenant_id or
                    manifest.principal != ctx.grant.principal or manifest.workflow != WORKFLOW_ID or
                    manifest.snapshot_id != ctx.grant.source_constraints["snapshot_id"] or
                    manifest.run_id != ctx.run_id):
                    return self._blocked_exec(ctx, "manifest_scope", "Manifest identity or scope does not match this task.")
                if not manifest.changes:
                    return self._blocked_exec(ctx, "nothing_to_repair", "The manifest has no changes, so nothing was committed.")
                change_keys = [(c.row_id, c.field) for c in manifest.changes]
                allowed_ids = set(ctx.grant.resources.get("order", []))
                if (len(change_keys) != len(set(change_keys)) or
                    any(rid not in allowed_ids or field not in ctx.grant.fields for rid, field in change_keys)):
                    return self._blocked_exec(ctx, "manifest_scope", "Manifest repeats a field or includes an ungranted record.")
                catalog = _field_catalog(conn, ctx.grant.source_constraints["dataset_id"])
                if not catalog or not set(ctx.grant.fields) <= set(catalog):
                    return self._blocked_exec(ctx, "field_catalog", "The repair field catalog is missing or changed.")
                snap = conn.execute("SELECT * FROM recovery.import_snapshots WHERE snapshot_id=%s", (manifest.snapshot_id,)).fetchone()
                if not snap or not self._snapshot_ok(snap, manifest.snapshot_digest) or snap["content_digest"] != ctx.grant.source_constraints["snapshot_digest"]:
                    return self._blocked_exec(ctx, "snapshot_digest", "Approved snapshot changed after preview.")
                # Same gate as executor.py: authority writers bump this row under FOR UPDATE, so it is shared here.
                conn.execute("SELECT epoch FROM authority.tenant_epochs WHERE tenant_id=%s FOR SHARE", (ctx.grant.tenant_id,)).fetchone()
                target_ids = list(manifest.preconditions.row_versions)
                rows = conn.execute("SELECT * FROM app.import_inventory_items WHERE dataset_id=%s AND record_id=ANY(%s) ORDER BY record_id FOR UPDATE", (ctx.grant.source_constraints["dataset_id"], target_ids)).fetchall()
                current = {r["record_id"]: r for r in rows}
                # Restore values are re-derived from the digest-covered source records, not the stored row copy.
                try:
                    restore = restore_values_from_source(snap["content"]["source_records"], snap["content"]["mapping"], catalog)
                except ImportInputError:
                    return self._blocked_exec(ctx, "snapshot_value", "Approved snapshot records no longer derive valid repair values.")
                # Authority rows that gate the write are shared-locked after the target rows, in key order.
                guards = self._guards(conn, ctx.grant.source_constraints["dataset_id"], target_ids, lock=True)
                revokes = self._revoked(conn, rows, lock=True)
                if any(not _values_match(row.get("repair_values"), catalog) for row in rows):
                    return self._blocked_exec(ctx, "field_catalog", "Current repair values do not match the dataset field catalog.")
                if any(not _values_match(values, catalog) for values in restore.values()):
                    return self._blocked_exec(ctx, "snapshot_value", "Approved snapshot values do not match the dataset field catalog.")
                for rid, version in manifest.preconditions.row_versions.items():
                    row = current.get(rid)
                    if not row or row["tenant_id"] != ctx.grant.tenant_id or int(row["row_version"]) != version:
                        return self._stale(ctx, "stale_row_version", f"Record {rid} changed after preview.")
                    reason = self._protect_reason(rid, guards, revokes)
                    if reason is None and int(row["row_version"]) > 2:
                        reason = "later_edit"
                    if reason:
                        return self._stale(ctx, "protected_record", f"Record {rid} is protected: {reason}.")
                conn.execute("SET LOCAL ROLE rs_import_executor")
                changes = []
                merged_values: dict[str, dict[str, Any]] = {}
                for change in manifest.changes:
                    if change.field not in catalog or change.field not in ctx.grant.fields:
                        return self._blocked_exec(ctx, "field_scope", "Manifest contains a field outside the dataset repair catalog or task grant.")
                    row = current.get(change.row_id)
                    values = merged_values.setdefault(change.row_id, dict(row["repair_values"]) if row else {})
                    if not row or row["repair_values"].get(change.field) != change.current_value:
                        return self._stale(ctx, "stale_row_version", f"Record {change.row_id} changed after preview.")
                    source = restore.get(change.row_id, {})
                    if change.field not in source or not _same_value(source[change.field], change.new_value):
                        return self._blocked_exec(ctx, "snapshot_value", "Manifest contains a value that is not in the approved snapshot.")
                    values[change.field] = change.new_value
                    changes.append(ReceiptChange(row_id=change.row_id, field=change.field, before=change.current_value, after=change.new_value))
                for rid, values in merged_values.items():
                    conn.execute("UPDATE app.import_inventory_items SET repair_values=%s,row_version=row_version+1,updated_at=now(),updated_by=%s WHERE dataset_id=%s AND record_id=%s AND tenant_id=%s",
                                 (Jsonb(to_jsonable(values)), "rewindsafe_import_executor", ctx.grant.source_constraints["dataset_id"], rid, ctx.grant.tenant_id))
                conn.execute("UPDATE runtime.task_grants SET commits_used=commits_used+1, status=CASE WHEN commits_used+1 >= max_commits THEN 'exhausted' ELSE status END WHERE grant_id=%s", (ctx.grant.grant_id,))
                conn.execute("UPDATE runtime.manifests SET status='committed' WHERE manifest_id=%s", (manifest.manifest_id,))
                receipt = ExecutionReceipt(operation_id=operation_id, idempotency_key=args["idempotency_key"], grant_id=ctx.grant.grant_id,
                    run_id=ctx.run_id, manifest_id=manifest.manifest_id, manifest_digest=manifest.content_digest,
                    result="committed", changes=changes, effect_counts={"rows_updated": len(merged_values)},
                    decision_sources=["rewindsafe.dispatch", "rewindsafe.import_recovery", "postgres.privilege"],
                    enforcement_mode=ctx.enforcement_mode, sdk_version=ctx.sdk_version,
                    fixture_generation=ctx.grant.fixture_generation, approval_id=ctx.approval.approval_id if ctx.approval else None,
                    created_at=utcnow(), committed_at=utcnow(), receipt_digest="sha256:pending")
                receipt = receipt.model_copy(update={"receipt_digest": digest(receipt.model_dump(mode="json", exclude={"receipt_digest"}))})
                conn.execute("INSERT INTO runtime.receipts(operation_id,grant_id,idempotency_key,run_id,manifest_id,manifest_digest,result,body,receipt_digest,fixture_generation) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (receipt.operation_id, receipt.grant_id, receipt.idempotency_key, receipt.run_id, receipt.manifest_id, receipt.manifest_digest, receipt.result, Jsonb(to_jsonable(receipt)), receipt.receipt_digest, receipt.fixture_generation))
            return ToolExecution(status=DispatchStatus.EXECUTED, observation={"status": "committed", "operation_id": receipt.operation_id, "receipt": to_jsonable(receipt)}, summary=f"Committed {len(changes)} imported field change(s).", receipt=receipt, state_changed=bool(changes))
        except Exception as exc:
            return ToolExecution(status=DispatchStatus.FAILED, observation={"status": "failed", "reason": type(exc).__name__}, summary="Inventory repair could not be committed.")

    def _receipt(self, ctx: ToolContext, args: dict[str, Any]) -> ToolExecution:
        with db.connection() as conn:
            if args.get("operation_id"):
                row = conn.execute("SELECT body FROM runtime.receipts WHERE operation_id=%s AND grant_id=%s", (args["operation_id"], ctx.grant.grant_id)).fetchone()
            elif args.get("manifest_id"):
                row = conn.execute("SELECT body FROM runtime.receipts WHERE manifest_id=%s AND grant_id=%s", (args["manifest_id"], ctx.grant.grant_id)).fetchone()
            else:
                row = conn.execute("SELECT body FROM runtime.receipts WHERE grant_id=%s ORDER BY created_at DESC LIMIT 1", (ctx.grant.grant_id,)).fetchone()
        if not row:
            return ToolExecution(status=DispatchStatus.EXECUTED, observation={"status": "not_found"}, summary="No inventory receipt exists yet.")
        receipt = ExecutionReceipt.model_validate(row["body"])
        return ToolExecution(status=DispatchStatus.EXECUTED, observation={"status": receipt.result, "receipt": to_jsonable(receipt)}, summary="Read the inventory repair receipt.", receipt=receipt)

    @staticmethod
    def _guards(conn: Any, dataset_id: str, ids: list[str], *, lock: bool = False) -> dict[str, dict[str, Any]]:
        # With lock, every row for these records is shared-locked, inactive holds included, so a concurrent
        # release, deletion or flag change waits for the apply transaction instead of racing its checks.
        share = " FOR SHARE" if lock else ""
        rows = conn.execute("SELECT t.* FROM authority.tombstones t JOIN app.import_inventory_items i ON i.record_id=t.entity_id AND i.tenant_id=t.tenant_id WHERE t.entity_type='inventory_item' AND t.entity_id=ANY(%s) AND i.dataset_id=%s ORDER BY t.entity_id" + (" FOR SHARE OF t" if lock else ""), (ids, dataset_id)).fetchall()
        tombs = {r["entity_id"]: r for r in rows}
        holds = {r["record_id"]: r for r in conn.execute("SELECT * FROM authority.import_record_holds WHERE dataset_id=%s AND record_id=ANY(%s) ORDER BY record_id" + share, (dataset_id, ids)).fetchall() if r["active"]}
        state_rows = conn.execute("SELECT * FROM recovery.import_authority_state WHERE dataset_id=%s AND record_id=ANY(%s) ORDER BY record_id" + share, (dataset_id, ids)).fetchall()
        states = {r["record_id"]: r for r in state_rows}
        return {rid: {"tombstone": tombs.get(rid) or states.get(rid, {}).get("tombstoned"),
                      "hold": holds.get(rid) or states.get(rid, {}).get("held"),
                      "revoked": states.get(rid, {}).get("revoked", False),
                      "later_edit": states.get(rid, {}).get("later_edit", False)} for rid in ids}

    @staticmethod
    def _revoked(conn: Any, rows: list[dict[str, Any]], *, lock: bool = False) -> set[str]:
        grants = {r["sync_grant_id"] for r in rows if r.get("sync_grant_id")}
        if not grants:
            return set()
        # Lock every matching grant row, not only revoked ones: a revocation is an update of an active row.
        statuses = conn.execute("SELECT grant_id,status FROM authority.access_grants WHERE grant_id=ANY(%s) ORDER BY grant_id" + (" FOR SHARE" if lock else ""), (list(grants),)).fetchall()
        revoked = {r["grant_id"] for r in statuses if r["status"] == "revoked"}
        return {r["record_id"] for r in rows if r.get("sync_grant_id") in revoked}

    @staticmethod
    def _protect_reason(rid: str, guards: dict[str, dict[str, Any]], revoked: set[str]) -> str | None:
        guard = guards.get(rid, {})
        if guard.get("tombstone"):
            return "tombstoned"
        if guard.get("hold"):
            return "held"
        if guard.get("revoked"):
            return "revoked"
        if guard.get("later_edit"):
            return "later_edit"
        if rid in revoked:
            return "revoked"
        return None

    @staticmethod
    def _snapshot_ok(snapshot: dict[str, Any], expected: str) -> bool:
        content = snapshot.get("content") or {}
        source_records = content.get("source_records")
        if not isinstance(source_records, list) or not isinstance(content.get("rows"), list):
            return False
        try:
            source_digest = digest(source_records)
        except (TypeError, ValueError):
            return False
        return bool(snapshot.get("approved") and snapshot.get("content_digest") == expected and source_digest == expected)

    def protected_checks(self, tenant_id: str) -> list[InvariantCheck]:
        with db.connection() as conn:
            datasets = conn.execute("SELECT dataset_id,current_rows FROM recovery.import_datasets WHERE tenant_id=%s OR tenant_id='multi'", (tenant_id,)).fetchall()
            checks = []
            for data in datasets:
                ids = [r["record_id"] for r in data["current_rows"] if r["tenant_id"] == tenant_id]
                if not ids:
                    continue
                guards = self._guards(conn, data["dataset_id"], ids)
                catalog = _field_catalog(conn, data["dataset_id"])
                current = {r["record_id"]: r for r in conn.execute(
                    "SELECT record_id,repair_values FROM app.import_inventory_items WHERE dataset_id=%s AND tenant_id=%s AND record_id=ANY(%s)",
                    (data["dataset_id"], tenant_id, ids),
                ).fetchall()}
                initial = {r["record_id"]: r for r in data["current_rows"]}
                categories = (("tombstone", "tombstoned"), ("access", "revoked"), ("hold", "hold"), ("later_update", "later_edit"))
                for category, flag in categories:
                    protected_ids = [rid for rid, flags in guards.items() if flags.get(flag)]
                    if not protected_ids:
                        continue
                    changed = any(
                        rid not in current or any(current[rid]["repair_values"].get(field) != initial[rid]["repair_values"].get(field) for field in catalog)
                        for rid in protected_ids
                    )
                    status = InvariantStatus.VIOLATED if changed else InvariantStatus.PRESERVED
                    labels = {"tombstone": "Tombstoned import records are unchanged", "access": "Revoked import records are unchanged",
                              "hold": "Held import records are unchanged", "later_update": "Later-edited import records are unchanged"}
                    checks.append(InvariantCheck(check_id=f"import:{category}:{data['dataset_id']}", label=labels[category], category=category, status=status))
        return checks

    def app_state(self, tenant_id: str) -> dict[str, Any]:
        with db.connection() as conn:
            rows = conn.execute("SELECT dataset_id,record_id,sku,quantity,location,repair_values,row_version FROM app.import_inventory_items WHERE tenant_id=%s ORDER BY dataset_id,record_id", (tenant_id,)).fetchall()
        return {"inventory_items": rows}

    @staticmethod
    def _block(ctx: ToolContext, invariant: str, reason: str) -> AdmissionResult:
        return AdmissionResult(decision=make_decision(ctx.run_id, DecisionSource.GRANT_SCOPE, Outcome.BLOCK, reason, proposal_id=ctx.proposal.proposal_id, invariant=invariant))

    @staticmethod
    def _blocked_exec(ctx: ToolContext, invariant: str, reason: str) -> ToolExecution:
        decision = make_decision(ctx.run_id, DecisionSource.DOMAIN, Outcome.BLOCK, reason, proposal_id=ctx.proposal.proposal_id, invariant=invariant)
        return ToolExecution(status=DispatchStatus.BLOCKED, observation={"status": "blocked", "reason": reason, "invariant": invariant}, summary=reason, decisions=[decision])

    @staticmethod
    def _stale(ctx: ToolContext, invariant: str, reason: str) -> ToolExecution:
        decision = make_decision(ctx.run_id, DecisionSource.PG_TRANSACTION, Outcome.BLOCK, reason, proposal_id=ctx.proposal.proposal_id, invariant=invariant)
        return ToolExecution(status=DispatchStatus.STALE, observation={"status": "stale", "reason": reason}, summary=reason, decisions=[decision])


ADAPTER = ImportRecoveryAdapter()
