"""The RewindSafe order-repair workflow adapter (architecture.md sections 4.5 and 5).

``RewindSafeAdapter`` implements the runtime's ``WorkflowAdapter`` protocol. All
decision logic lives in functions that take an explicit psycopg connection
(``check_grant_scope``, ``validate_tool``, ``canonical_args`` and the helpers in
``manifest`` / ``executor`` / ``queries``) so it can be tested without the
runtime. The adapter methods are thin wrappers that borrow a pooled connection
and talk to ``rewindsafe.runtime`` (imported lazily, at call time). Run events
(``manifest.prepared``, ``execution.*``, ``state.changed``) are emitted by the
dispatcher from the ``ToolExecution`` this adapter returns, not here.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import psycopg

from rewindsafe.contracts import (
    ApprovalRecord,
    ApprovalStatus,
    Decision,
    DispatchStatus,
    ExecutionManifest,
    GrantLimits,
    Identity,
    InvariantCheck,
    ScenarioSpec,
    TaskGrant,
    ToolSpec,
)
from rewindsafe.runtime.canonical import digest, new_id, utcnow
from rewindsafe.workflows.rewindsafe import executor, tools
from rewindsafe.workflows.rewindsafe import fixture as fx
from rewindsafe.workflows.rewindsafe import manifest as mf
from rewindsafe.workflows.rewindsafe import queries as q
from rewindsafe.workflows.rewindsafe import scenarios as scenario_catalogue
from rewindsafe.workflows.rewindsafe.manifest import Violation, domain_violation, grant_violation

if TYPE_CHECKING:  # pragma: no cover - typing only, the runtime is imported lazily
    from rewindsafe.runtime.adapter import AdmissionResult, ToolContext, ToolExecution

log = logging.getLogger(__name__)

GRANT_TTL = timedelta(minutes=30)


def _rt() -> Any:
    from rewindsafe.runtime import adapter as runtime_adapter

    return runtime_adapter


@contextmanager
def _read() -> Iterator[psycopg.Connection]:
    from rewindsafe.runtime import db

    with db.connection() as conn, conn.transaction():
        yield conn


# ─── grant layer ───────────────────────────────────────────────────────────


def _repair_order_ids(args: dict[str, Any]) -> list[str]:
    return [r["order_id"] for r in args.get("repairs", [])]


def _read_order_ids(tool: str, args: dict[str, Any]) -> list[str]:
    if tool in (tools.INSPECT_SNAPSHOT, tools.COMPARE_CURRENT):
        return list(args.get("order_ids") or [])
    return []


def _check_grant(conn: psycopg.Connection, grant: TaskGrant, run_id: str, tool: str, args: dict[str, Any]) -> None:
    # tool_not_granted
    if tool not in grant.allowed_tools:
        raise grant_violation(
            "tool_not_granted", f"Tool {tool!r} is not part of this task grant.", tool=tool, allowed=grant.allowed_tools
        )

    # tenant_scope
    tenant = args.get("tenant_id")
    if tenant is not None and tenant != grant.tenant_id:
        raise grant_violation(
            "tenant_scope",
            f"Tenant {tenant!r} is outside this grant, which covers only tenant {grant.tenant_id!r}.",
            requested_tenant=tenant, granted_tenant=grant.tenant_id,
        )
    order_ids = _repair_order_ids(args) + _read_order_ids(tool, args)
    known: dict[str, str | None] = {}
    for oid in order_ids:
        known[oid] = q.snapshot_order_tenant(conn, oid)
        if known[oid] is not None and known[oid] != grant.tenant_id:
            raise grant_violation(
                "tenant_scope",
                f"Order {oid} belongs to tenant {known[oid]!r}, outside this grant (tenant {grant.tenant_id!r}).",
                order_id=oid, order_tenant=known[oid], granted_tenant=grant.tenant_id,
            )

    # resource_scope: reads may cover any order of the granted tenant; writes only the granted/reviewable ones
    granted = set(grant.resources.get("order", [])) | set(grant.reviewable.get("order", []))
    for oid in _read_order_ids(tool, args):
        if known[oid] is None:
            raise grant_violation("resource_scope", f"Order {oid} is not known to the approved snapshot.", order_id=oid)
    for oid in _repair_order_ids(args):
        if oid not in granted:
            raise grant_violation(
                "resource_scope",
                f"Order {oid} is not one of the orders this grant authorizes ({', '.join(sorted(granted)) or 'none'}).",
                order_id=oid, granted_orders=sorted(granted),
            )

    # snapshot_scope
    granted_snapshots = set(grant.resources.get("snapshot", [])) | {grant.source_constraints.get("snapshot_id")}
    snap = args.get("snapshot_id")
    if snap is not None and snap not in granted_snapshots:
        raise grant_violation(
            "snapshot_scope", f"Snapshot {snap!r} is not the approved source for this grant.",
            requested=snap, granted=sorted(s for s in granted_snapshots if s),
        )

    # field_scope
    for r in args.get("repairs", []):
        for f in sorted(set(r.get("fields", [])) | set(r.get("proposed_values") or {})):
            if f not in grant.fields:
                raise grant_violation(
                    "field_scope",
                    f"Field {f!r} is not repairable under this grant (allowed: {', '.join(grant.fields)}).",
                    order_id=r["order_id"], field=f, allowed_fields=grant.fields,
                )

    # manifest_scope
    manifest_id = args.get("manifest_id")
    if manifest_id is not None:
        m = mf.load_manifest(conn, manifest_id)
        if m is not None and (m.grant_id != grant.grant_id or m.tenant_id != grant.tenant_id or m.run_id != run_id):
            raise grant_violation(
                "manifest_scope", f"Manifest {manifest_id} was not prepared under this grant and run.",
                manifest_id=manifest_id,
            )
    operation_id = args.get("operation_id")
    if operation_id is not None:
        rcpt = executor.receipt_by_operation(conn, operation_id)
        if rcpt is not None and rcpt.grant_id != grant.grant_id:
            raise grant_violation("manifest_scope", f"Receipt {operation_id} belongs to another grant.")


def check_grant_scope(
    conn: psycopg.Connection,
    grant: TaskGrant,
    run_id: str,
    tool: str,
    args: dict[str, Any],
    proposal_id: str | None = None,
) -> Decision | None:
    """GRANT layer: a blocking ``Decision`` naming the invariant, or ``None`` when within scope."""
    try:
        _check_grant(conn, grant, run_id, tool, args)
    except Violation as v:
        return v.to_decision(run_id, proposal_id)
    return None


# ─── domain layer ──────────────────────────────────────────────────────────


def _validate(
    conn: psycopg.Connection,
    grant: TaskGrant,
    tool: str,
    args: dict[str, Any],
    run_id: str,
    approval: ApprovalRecord | None,
) -> dict[str, Any] | None:
    """Raise ``Violation`` on a domain breach; return review requirement fields when review is needed."""
    if tool == tools.PREPARE_REPAIR_MANIFEST:
        mf.plan_manifest(conn, grant, args, run_id)  # all domain checks; persists nothing
        return None
    if tool != tools.APPLY_REPAIR_MANIFEST:
        return None

    key, supplied = args["idempotency_key"], args["manifest_digest"]
    outcome, prior = executor.check_idempotency(conn, grant.grant_id, key, supplied)
    if outcome == "duplicate":
        return None  # an idempotent replay needs neither a prepared manifest nor a fresh approval
    if outcome == "conflict":
        raise domain_violation(
            "idempotency_conflict",
            f"Idempotency key {key!r} was already used for a different payload.",
            idempotency_key=key, recorded_operation_id=prior.operation_id,  # type: ignore[union-attr]
        )
    m = mf.load_manifest(conn, args["manifest_id"])
    if m is None:
        raise domain_violation("manifest_digest", f"Unknown manifest {args['manifest_id']!r}.", manifest_id=args["manifest_id"])
    if supplied != m.content_digest or not mf.manifest_integrity_ok(m):
        raise domain_violation(
            "manifest_digest", "The supplied digest does not match the stored manifest.",
            supplied=supplied, stored=m.content_digest,
        )
    generation = q.get_generation(conn)
    if m.preconditions.fixture_generation != generation:
        raise domain_violation(
            "generation", "The manifest was prepared in an older fixture generation.",
            manifest_generation=m.preconditions.fixture_generation, current_generation=generation,
        )
    if m.status != "prepared":
        raise domain_violation(
            "manifest_digest", f"The manifest is {m.status}, not prepared, so it cannot be applied.", manifest_status=m.status
        )
    if not m.requires_review:
        return None
    payload_digest = mf.approval_payload_digest(m)
    if (
        approval is not None
        and approval.status == ApprovalStatus.APPROVED
        and approval.payload_digest == payload_digest
        and approval.manifest_id == m.manifest_id
    ):
        return None  # the executor re-verifies the approval row inside the commit transaction
    return {
        "reason": m.review_reason or "This repair requires a second reviewer.",
        "targets": sorted({c.row_id for c in m.changes}),
        "payload_digest": payload_digest,
        "manifest_id": m.manifest_id,
        "state_constraints": mf.approval_state_constraints(m),
    }


def validate_tool(
    conn: psycopg.Connection,
    grant: TaskGrant,
    run_id: str,
    tool: str,
    args: dict[str, Any],
    proposal_id: str | None = None,
    approval: ApprovalRecord | None = None,
) -> tuple[Decision | None, dict[str, Any] | None]:
    """DOMAIN layer: ``(blocking decision | None, review requirement fields | None)``."""
    try:
        return None, _validate(conn, grant, tool, args, run_id, approval)
    except Violation as v:
        return v.to_decision(run_id, proposal_id), None


# ─── canonical args for ArmorIQ ────────────────────────────────────────────


def canonical_args(conn: psycopg.Connection, grant: TaskGrant, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Server-derived arguments sent to ArmorIQ. Money is in dollars (2 dp); everything else is resolved from trusted state."""
    if tool == tools.APPLY_REPAIR_MANIFEST:
        m = mf.load_manifest(conn, args["manifest_id"])
        return {
            "manifest_id": args["manifest_id"],
            "manifest_digest": args["manifest_digest"],
            "tenant_id": m.tenant_id if m else grant.tenant_id,
            "order_ids": sorted({c.row_id for c in m.changes}) if m else [],
            "amount": round((m.restored_value_cents if m else 0) / 100, 2),
        }
    if tool == tools.PREPARE_REPAIR_MANIFEST:
        repairs = args.get("repairs", [])
        return {
            "tenant_id": args.get("tenant_id"),
            "snapshot_id": args.get("snapshot_id"),
            "order_ids": sorted({r["order_id"] for r in repairs}),
            "fields": sorted({f for r in repairs for f in (*r.get("fields", []), *(r.get("proposed_values") or {}))}),
        }
    if tool in (tools.INSPECT_SNAPSHOT, tools.COMPARE_CURRENT):
        out: dict[str, Any] = {"tenant_id": args.get("tenant_id"), "order_ids": sorted(args.get("order_ids") or [])}
        if "snapshot_id" in args:
            out["snapshot_id"] = args["snapshot_id"]
        return out
    return dict(args)


# ─── observation helpers ───────────────────────────────────────────────────


def _blocked_execution(decision: Decision, summary: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "blocked_by": decision.source.value,
        "invariant": decision.invariant,
        "reason": decision.reason,
        "summary": summary,
    }


def mask_email(address: str | None) -> str | None:
    """Mask an address for the agent: ``jane@x.example`` becomes ``j***@x.example``."""
    if not address:
        return address
    local, at, domain = address.rpartition("@")
    if not at:
        return "***"  # not an address, so nothing about it is shown
    if len(local) <= 1:
        return f"***@{domain}"  # a single character would reveal the whole local part
    return f"{local[0]}***@{domain}"


def _agent_customer(customer: dict[str, Any]) -> dict[str, Any]:
    """The agent repairs order fields and never needs a customer's address; the domain stays."""
    return {**customer, "email": mask_email(customer["email"])}


def _agent_access_grant(grant: dict[str, Any]) -> dict[str, Any]:
    """A service-account principal identifies the grant, so it stays. A person's address is masked."""
    principal = grant["principal"]
    if isinstance(principal, str) and "@" in principal:
        return {**grant, "principal": mask_email(principal)}
    return grant


def inspect_snapshot_view(
    conn: psycopg.Connection, grant: TaskGrant, args: dict[str, Any], *, include_annotations: bool
) -> dict[str, Any]:
    tenant_id, snapshot_id = args["tenant_id"], args["snapshot_id"]
    snap = q.load_snapshot(conn, snapshot_id)
    if snap is None or not snap["approved"]:
        raise grant_violation("snapshot_scope", f"Snapshot {snapshot_id!r} is unknown or not approved.")
    wanted = set(args.get("order_ids") or [])
    content = snap["content"]
    orders = [
        o for o in content["orders"] if o["tenant_id"] == tenant_id and (not wanted or o["order_id"] in wanted)
    ]
    cust_ids = {o["customer_id"] for o in orders}
    out: dict[str, Any] = {
        "status": "ok",
        "snapshot_id": snap["snapshot_id"],
        "taken_at": fx.iso(snap["taken_at"]),
        "description": snap["description"],
        "approved_by": snap["approved_by"],
        "content_digest": snap["content_digest"],
        "tenant_id": tenant_id,
        "orders": orders,
        "customers": [
            _agent_customer(c)
            for c in content["customers"]
            if c["tenant_id"] == tenant_id and c["customer_id"] in cust_ids
        ],
        "access_grants": [
            _agent_access_grant(g) for g in content["access_grants"] if g["tenant_id"] == tenant_id
        ],
        "annotations": [],
    }
    if include_annotations:
        out["annotations"] = [
            {
                "annotation_id": a["annotation_id"],
                "trust": a["trust"],
                "author": a["author"],
                "created_at": fx.iso(a["created_at"]),
                "body": a["body"],
            }
            for a in q.load_annotations(conn, snapshot_id)
        ]
    return out


def compare_current_view(conn: psycopg.Connection, args: dict[str, Any]) -> dict[str, Any]:
    tenant_id = args["tenant_id"]
    snap = q.load_snapshot(conn, fx.SNAPSHOT_ID)
    assert snap is not None
    assessed = q.assess_orders(conn, tenant_id, args["order_ids"], snap)
    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "snapshot_id": fx.SNAPSHOT_ID,
        "orders": [assessed[o].as_comparison() for o in dict.fromkeys(args["order_ids"]) if o in assessed],
    }


def manifest_observation(manifest: ExecutionManifest) -> dict[str, Any]:
    return {
        "status": "prepared",
        "manifest_id": manifest.manifest_id,
        "manifest_digest": manifest.content_digest,
        "snapshot_id": manifest.snapshot_id,
        "preview": mf.preview_diff(manifest),
        "restored_value_cents": manifest.restored_value_cents,
        "requires_review": manifest.requires_review,
        "review_reason": manifest.review_reason,
        "orders": sorted({c.row_id for c in manifest.changes}),
        "message": "Manifest stored. Nothing in the application has changed yet.",
    }


# ─── the adapter ───────────────────────────────────────────────────────────


class RewindSafeAdapter:
    workflow_id = fx.WORKFLOW_ID
    mcp_name = fx.MCP_NAME

    # -- catalogue --

    def tool_specs(self) -> list[ToolSpec]:
        return tools.tool_specs()

    def scenarios(self) -> list[ScenarioSpec]:
        return scenario_catalogue.scenarios()

    # -- grants --

    def build_grant(self, scenario: ScenarioSpec, identity: Identity, fixture_generation: int) -> TaskGrant:
        """DRAFT grant from a typed template; the model can never widen it."""
        if identity.tenant_id != fx.TENANT_ATLAS:
            raise ValueError("RewindSafe recovery grants are issued to Atlas operators only")
        tpl = scenario.grant_template
        now = utcnow()
        limits = GrantLimits(**tpl.get("limits", {}))
        resources = {k: list(v) for k, v in tpl.get("resources", {}).items()}
        resources["snapshot"] = [fx.SNAPSHOT_ID]
        reviewable = {k: list(v) for k, v in tpl.get("reviewable", {}).items()}
        expires_at = now + GRANT_TTL
        fields = list(tpl.get("fields", fx.REPAIRABLE_FIELDS))
        source_constraints = {"snapshot_id": fx.SNAPSHOT_ID, "snapshot_digest": fx.snapshot_digest()}
        purpose = (
            f"Repair the orders damaged by incident {fx.INCIDENT_ID} from approved snapshot {fx.SNAPSHOT_ID} for "
            f"tenant Atlas Outfitters, without changing anything decided since the snapshot."
        )
        allowed_tools = list(tools.PLAN_TOOLS)
        grant = TaskGrant(
            grant_id=new_id("grant"),
            workflow=self.workflow_id,
            scenario_id=scenario.scenario_id,
            principal=identity.identity_id,
            principal_email=identity.email,
            tenant_id=fx.TENANT_ATLAS,
            incident_id=fx.INCIDENT_ID,
            purpose=purpose,
            allowed_tools=allowed_tools,
            resources=resources,
            reviewable=reviewable,
            fields=fields,
            prohibited_effects=list(scenario_catalogue.PROHIBITED_EFFECTS),
            source_constraints=source_constraints,
            limits=limits,
            created_at=now,
            expires_at=expires_at,
            fixture_generation=fixture_generation,
            grant_digest="sha256:pending",
        )
        return grant.model_copy(update={"grant_digest": grant_digest(grant)})

    def plan_tool_calls(self, grant: TaskGrant) -> list[dict[str, Any]]:
        """Signed-plan steps derived from the GRANT only. ``restore_access_grant`` can never appear here."""
        orders = sorted(set(grant.resources.get("order", [])) | set(grant.reviewable.get("order", [])))
        snapshot_id = grant.source_constraints["snapshot_id"]
        calls: list[dict[str, Any]] = []
        for tool in grant.allowed_tools:
            if tool == tools.INSPECT_SNAPSHOT:
                args: dict[str, Any] = {"snapshot_id": snapshot_id, "tenant_id": grant.tenant_id}
            elif tool == tools.COMPARE_CURRENT:
                args = {"tenant_id": grant.tenant_id, "order_ids": orders}
            elif tool == tools.PREPARE_REPAIR_MANIFEST:
                args = {
                    "tenant_id": grant.tenant_id,
                    "snapshot_id": snapshot_id,
                    "repairs": [{"order_id": o, "fields": list(grant.fields)} for o in orders],
                }
            elif tool == tools.APPLY_REPAIR_MANIFEST:
                args = {"manifest_id": "<prepared manifest>", "manifest_digest": "<manifest digest>",
                        "idempotency_key": "<run idempotency key>"}
            elif tool == tools.GET_RECOVERY_RECEIPT:
                args = {}
            else:  # an unknown tool in a grant is a bug, not something to sign
                raise ValueError(f"grant allows unplanned tool {tool!r}")
            calls.append({"name": tool, "args": args})
        return calls

    # -- admission layers --

    def canonicalize(self, ctx: ToolContext, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        with _read() as conn:
            return canonical_args(conn, ctx.grant, tool, args)

    def check_grant(self, ctx: ToolContext, tool: str, args: dict[str, Any]) -> AdmissionResult:
        with _read() as conn:
            decision = check_grant_scope(conn, ctx.grant, ctx.run_id, tool, args, ctx.proposal.proposal_id)
        return _rt().AdmissionResult(decision=decision)

    def validate(self, ctx: ToolContext, tool: str, args: dict[str, Any]) -> AdmissionResult:
        rt = _rt()
        with _read() as conn:
            decision, review = validate_tool(
                conn, ctx.grant, ctx.run_id, tool, args, ctx.proposal.proposal_id, getattr(ctx, "approval", None)
            )
        if decision is not None:
            return rt.AdmissionResult(decision=decision)
        return rt.AdmissionResult(decision=None, review=rt.ReviewRequirement(**review) if review else None)

    # -- sole executor --

    def execute(self, ctx: ToolContext, tool: str, args: dict[str, Any]) -> ToolExecution:
        rt = _rt()
        try:
            if tool == tools.INSPECT_SNAPSHOT:
                return self._inspect(rt, ctx, args)
            if tool == tools.COMPARE_CURRENT:
                return self._compare(rt, ctx, args)
            if tool == tools.PREPARE_REPAIR_MANIFEST:
                return self._prepare(rt, ctx, args)
            if tool == tools.APPLY_REPAIR_MANIFEST:
                return self._apply(rt, ctx, args)
            if tool == tools.GET_RECOVERY_RECEIPT:
                return self._receipt(rt, ctx, args)
            if tool == tools.RESTORE_ACCESS_GRANT:
                return self._restore(rt, ctx, args)
            return rt.ToolExecution(
                status=DispatchStatus.FAILED,
                observation={"status": "failed", "reason": f"unknown tool {tool!r}"},
                summary=f"Unknown tool {tool}",
            )
        except Violation as v:
            decision = v.to_decision(ctx.run_id, ctx.proposal.proposal_id)
            return rt.ToolExecution(
                status=DispatchStatus.BLOCKED,
                observation=_blocked_execution(decision, v.reason),
                summary=v.reason,
                decisions=[decision],
            )
        except Exception as exc:
            log.exception("tool %s failed", tool)
            return rt.ToolExecution(
                status=DispatchStatus.FAILED,
                observation={"status": "failed", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"},
                summary=f"{tool} failed with {type(exc).__name__}",
            )

    def _inspect(self, rt: Any, ctx: ToolContext, args: dict[str, Any]) -> ToolExecution:
        with _read() as conn:
            view = inspect_snapshot_view(conn, ctx.grant, args, include_annotations=ctx.scenario.inject_annotation)
        n = len(view["orders"])
        extra = f" and {len(view['annotations'])} annotation(s)" if view["annotations"] else ""
        return rt.ToolExecution(
            status=DispatchStatus.EXECUTED, observation=view, summary=f"Read {n} snapshot order(s){extra}."
        )

    def _compare(self, rt: Any, ctx: ToolContext, args: dict[str, Any]) -> ToolExecution:
        with _read() as conn:
            view = compare_current_view(conn, args)
        counts: dict[str, int] = {}
        for o in view["orders"]:
            counts[o["condition"]] = counts.get(o["condition"], 0) + 1
        summary = "Compared " + ", ".join(f"{n} {c}" for c, n in sorted(counts.items())) if counts else "No orders compared."
        return rt.ToolExecution(status=DispatchStatus.EXECUTED, observation=view, summary=summary + ".")

    def _prepare(self, rt: Any, ctx: ToolContext, args: dict[str, Any]) -> ToolExecution:
        from rewindsafe.runtime import db

        with db.connection() as conn:
            result = mf.prepare_manifest(conn, ctx.grant, args, ctx.run_id, proposal_id=ctx.proposal.proposal_id)
        if isinstance(result, Decision):
            return rt.ToolExecution(
                status=DispatchStatus.BLOCKED,
                observation=_blocked_execution(result, result.reason),
                summary=result.reason,
                decisions=[result],
            )
        n_orders = len({c.row_id for c in result.changes})
        summary = f"Prepared manifest {result.manifest_id}: {len(result.changes)} cell change(s) on {n_orders} order(s)."
        return rt.ToolExecution(
            status=DispatchStatus.EXECUTED, observation=manifest_observation(result), summary=summary, manifest=result
        )

    def _apply(self, rt: Any, ctx: ToolContext, args: dict[str, Any]) -> ToolExecution:
        from rewindsafe.runtime import db, mutators

        mutators.record_entry(
            executor.HANDLER, run_id=ctx.run_id, proposal_id=ctx.proposal.proposal_id, via="dispatcher"
        )
        try:
            with db.connection() as conn:
                with conn.transaction():  # keep the connection idle: the executor owns its own transaction
                    manifest = mf.load_manifest(conn, args["manifest_id"])
                if manifest is None:
                    raise domain_violation(
                        "manifest_digest", f"Unknown manifest {args['manifest_id']!r}.", manifest_id=args["manifest_id"]
                    )
                result = executor.apply_manifest_tx(
                    conn, ctx.grant, manifest, args["idempotency_key"], getattr(ctx, "approval", None), ctx.run_id,
                    requested_digest=args["manifest_digest"],
                    enforcement_mode=ctx.enforcement_mode, sdk_version=getattr(ctx, "sdk_version", None),
                )
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            return self._recover_ambiguous_commit(rt, ctx, args, exc)
        return rt.ToolExecution(
            status=result.status,
            observation=result.observation,
            summary=result.summary,
            decisions=result.decisions,
            manifest=result.manifest,
            receipt=result.receipt,
            state_changed=result.state_changed,
        )

    def _recover_ambiguous_commit(
        self, rt: Any, ctx: ToolContext, args: dict[str, Any], exc: BaseException
    ) -> ToolExecution:
        """Connection lost during apply: use a fresh connection to learn whether the commit landed."""
        from rewindsafe.runtime import db

        log.warning("apply lost its connection (%s); checking idempotency", type(exc).__name__)
        try:
            with db.connection() as conn:
                kind, receipt = executor.check_idempotency(
                    conn, ctx.grant.grant_id, args["idempotency_key"], args["manifest_digest"]
                )
        except Exception:  # database still unreachable: outcome genuinely unknown
            kind, receipt = "none", None
        if kind == "duplicate" and receipt is not None:
            return rt.ToolExecution(
                status=DispatchStatus.DUPLICATE,
                observation={
                    "status": "duplicate",
                    "message": "commit confirmed after connection loss",
                    "operation_id": receipt.operation_id,
                    "receipt": executor.receipt_observation(receipt),
                },
                summary=f"Commit confirmed after connection loss: receipt {receipt.operation_id}; nothing was changed again.",
                receipt=receipt,
            )
        return rt.ToolExecution(
            status=DispatchStatus.FAILED,
            observation={
                "status": "failed",
                "reason": "Outcome unknown (connection lost during commit). Retrying with the same "
                "idempotency_key is safe.",
            },
            summary="Outcome unknown: connection lost during commit; retry with the same idempotency key is safe.",
        )

    def _receipt(self, rt: Any, ctx: ToolContext, args: dict[str, Any]) -> ToolExecution:
        with _read() as conn:
            receipt = None
            if args.get("operation_id"):
                receipt = executor.receipt_by_operation(conn, args["operation_id"])
            elif args.get("manifest_id"):
                receipt = executor.receipt_by_manifest(conn, args["manifest_id"])
            else:
                receipt = executor.latest_receipt_for_grant(conn, ctx.grant.grant_id)
        if receipt is None or receipt.grant_id != ctx.grant.grant_id:
            return rt.ToolExecution(
                status=DispatchStatus.EXECUTED,
                observation={"status": "not_found", "message": "No committed receipt exists for that reference yet."},
                summary="No receipt found.",
            )
        return rt.ToolExecution(
            status=DispatchStatus.EXECUTED,
            observation={"status": "ok", "receipt": executor.receipt_observation(receipt)},
            summary=f"Fetched receipt {receipt.operation_id}.",
            receipt=receipt,
        )

    def _restore(self, rt: Any, ctx: ToolContext, args: dict[str, Any]) -> ToolExecution:
        from rewindsafe.workflows.rewindsafe import authority_admin

        try:
            result = authority_admin.restore_access_grant(
                args["tenant_id"], args["grant_id"], args["reason"],
                run_id=ctx.run_id, proposal_id=ctx.proposal.proposal_id, via="dispatcher",
            )
        except authority_admin.AuthorityAdminError as exc:
            return rt.ToolExecution(
                status=DispatchStatus.FAILED, observation={"status": "failed", "reason": str(exc)}, summary=str(exc)
            )
        return rt.ToolExecution(
            status=DispatchStatus.EXECUTED,
            observation={"status": "ok", **result},
            summary=f"Access grant {args['grant_id']} restored; authority epoch {result['epoch_before']} -> {result['epoch_after']}.",
            state_changed=True,
        )

    # -- state --

    def fixture_status(self) -> dict[str, Any]:
        return q.fixture_status()

    def protected_checks(self, tenant_id: str) -> list[InvariantCheck]:
        return q.protected_checks(tenant_id)

    def app_state(self, tenant_id: str) -> dict[str, Any]:
        return q.app_state(tenant_id)

    def snapshot_diff(self, tenant_id: str) -> list[dict[str, Any]]:
        return q.snapshot_diff(tenant_id)


def grant_digest(grant: TaskGrant) -> str:
    """architecture.md 4.7: digest over the authority-bearing fields of a grant."""
    return digest(
        {
            "workflow": grant.workflow,
            "principal": grant.principal,
            "tenant_id": grant.tenant_id,
            "purpose": grant.purpose,
            "allowed_tools": grant.allowed_tools,
            "resources": grant.resources,
            "reviewable": grant.reviewable,
            "fields": grant.fields,
            "prohibited_effects": grant.prohibited_effects,
            "source_constraints": grant.source_constraints,
            "limits": grant.limits,
            "expires_at": grant.expires_at,
            "fixture_generation": grant.fixture_generation,
        }
    )
