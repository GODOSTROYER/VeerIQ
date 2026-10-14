"""Execution manifests: how a repair request becomes an immutable, digest-bound plan of exact effects.

Trusted code resolves every new value from the approved snapshot. A model (or
any caller) can only say *which* orders and fields to repair; it can never
supply a value, an SQL statement or a different tenant. Violations surface as
typed ``Violation`` exceptions that carry the layer, source and invariant id
required by architecture.md section 5.4, and convert to ``Decision`` objects.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from rewindsafe.contracts import (
    Decision,
    DecisionSource,
    ExecutionManifest,
    Layer,
    ManifestChange,
    ManifestPreconditions,
    Outcome,
    TaskGrant,
)
from rewindsafe.runtime.canonical import digest, new_id, utcnow
from rewindsafe.workflows.rewindsafe import fixture as fx
from rewindsafe.workflows.rewindsafe import queries as q


class Violation(Exception):
    """A blocked request: which layer says no, and under which named invariant."""

    def __init__(
        self,
        layer: Layer,
        source: DecisionSource,
        invariant: str,
        reason: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{invariant}: {reason}")
        self.layer = layer
        self.source = source
        self.invariant = invariant
        self.reason = reason
        self.evidence = evidence or {}

    def to_decision(self, run_id: str, proposal_id: str | None = None) -> Decision:
        return make_decision(
            run_id,
            self.layer,
            self.source,
            Outcome.BLOCK,
            self.reason,
            invariant=self.invariant,
            proposal_id=proposal_id,
            evidence=self.evidence,
        )


def make_decision(
    run_id: str,
    layer: Layer,
    source: DecisionSource,
    outcome: Outcome,
    reason: str,
    *,
    invariant: str | None = None,
    proposal_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> Decision:
    """Build a RewindSafe-side ``Decision``. Never used for ArmorIQ verdicts."""
    return Decision(
        decision_id=new_id("dec"),
        run_id=run_id,
        proposal_id=proposal_id,
        layer=layer,
        source=source,
        outcome=outcome,
        decisive=outcome in (Outcome.BLOCK, Outcome.HOLD),
        shadow=False,
        simulated=False,
        reason=reason,
        invariant=invariant,
        evidence=evidence or {},
        created_at=utcnow(),
    )


def grant_violation(invariant: str, reason: str, **evidence: Any) -> Violation:
    return Violation(Layer.GRANT, DecisionSource.GRANT_SCOPE, invariant, reason, evidence)


def domain_violation(invariant: str, reason: str, **evidence: Any) -> Violation:
    return Violation(Layer.DOMAIN, DecisionSource.DOMAIN, invariant, reason, evidence)


# ─── digests ───────────────────────────────────────────────────────────────


def compute_content_digest(manifest: ExecutionManifest) -> str:
    """sha256 over everything except status, created_at and the digest itself."""
    body = manifest.model_dump(mode="json", exclude={"status", "created_at", "content_digest"})
    return digest(body)


def manifest_integrity_ok(manifest: ExecutionManifest) -> bool:
    return compute_content_digest(manifest) == manifest.content_digest


def approval_payload_digest(manifest: ExecutionManifest) -> str:
    """Digest an approval is bound to: the exact apply payload (tool, manifest, every cell, state constraints)."""
    return digest(
        {
            "tool": "apply_repair_manifest",
            "manifest_id": manifest.manifest_id,
            "manifest_digest": manifest.content_digest,
            "tenant_id": manifest.tenant_id,
            "changes": [
                [c.row_id, c.field, c.current_value, c.new_value]
                for c in manifest.changes
            ],
            "state_constraints": manifest.preconditions.model_dump(mode="json"),
        }
    )


def approval_state_constraints(manifest: ExecutionManifest) -> dict[str, Any]:
    return manifest.preconditions.model_dump(mode="json")


# ─── value comparison ──────────────────────────────────────────────────────


def values_equal(a: Any, b: Any) -> bool:
    """Strict equality that does not let ``True == 1`` or ``1 == 1.0`` smuggle a different value."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if type(a) is not type(b):
        return False
    return a == b


# ─── planning ──────────────────────────────────────────────────────────────


def plan_manifest(
    conn: psycopg.Connection, grant: TaskGrant, args: dict[str, Any], run_id: str
) -> ExecutionManifest:
    """Resolve a repair request into a manifest or raise ``Violation``. Writes nothing."""
    tenant_id = args["tenant_id"]
    snapshot_id = args["snapshot_id"]
    repairs: list[dict[str, Any]] = args["repairs"]

    # Defense in depth: the grant layer has already checked these, the executor never relies on that.
    if tenant_id != grant.tenant_id:
        raise grant_violation(
            "tenant_scope", f"Tenant {tenant_id!r} is outside this grant (tenant {grant.tenant_id!r}).",
            requested=tenant_id, granted=grant.tenant_id,
        )
    granted_snapshot = grant.source_constraints.get("snapshot_id")
    if snapshot_id != granted_snapshot:
        raise grant_violation(
            "snapshot_scope", f"Snapshot {snapshot_id!r} is not the approved source for this grant.",
            requested=snapshot_id, granted=granted_snapshot,
        )

    # Read the authority epoch FIRST: anything that changes authority after this read moves the epoch,
    # so the commit-time check against this value cannot miss it.
    epoch = q.get_epoch(conn, tenant_id)
    generation = q.get_generation(conn)
    if generation != grant.fixture_generation:
        raise domain_violation(
            "generation", "The grant belongs to an older fixture generation.",
            grant_generation=grant.fixture_generation, current_generation=generation,
        )

    snapshot = q.load_snapshot(conn, snapshot_id)
    if snapshot is None or not snapshot["approved"]:
        raise grant_violation("snapshot_scope", f"Snapshot {snapshot_id!r} is unknown or not approved.")
    if digest(snapshot["content"]) != snapshot["content_digest"]:
        raise domain_violation("snapshot_value", "Snapshot content does not match its recorded digest.")
    expected_digest = grant.source_constraints.get("snapshot_digest")
    if expected_digest and expected_digest != snapshot["content_digest"]:
        raise grant_violation("snapshot_scope", "Snapshot digest differs from the one the grant was issued for.")

    order_ids = [r["order_id"] for r in repairs]
    if len(set(order_ids)) != len(order_ids):
        raise domain_violation("duplicate_repair", "Each order may appear only once per manifest.")
    if len(order_ids) > grant.limits.max_rows_per_commit:
        raise domain_violation(
            "row_limit",
            f"{len(order_ids)} orders exceed the grant's limit of {grant.limits.max_rows_per_commit} per commit.",
        )

    snap_orders = q.snapshot_orders_by_id(snapshot)

    # 1. request validity: fields and proposed values (a value can only ever come from the snapshot)
    for r in repairs:
        oid = r["order_id"]
        snap_row = snap_orders.get(oid)
        if snap_row is None:
            raise grant_violation("resource_scope", f"Order {oid} is not part of the approved snapshot.", order_id=oid)
        if snap_row["tenant_id"] != tenant_id:
            raise grant_violation(
                "tenant_scope", f"Order {oid} belongs to another tenant.", order_id=oid, order_tenant=snap_row["tenant_id"]
            )
        proposed = r.get("proposed_values") or {}
        fields = set(r["fields"]) | set(proposed)
        for f in sorted(fields):
            if f not in grant.fields:
                raise grant_violation(
                    "field_scope", f"Field {f!r} is not repairable under this grant.", order_id=oid, field=f
                )
        for f, value in sorted(proposed.items()):
            if not values_equal(value, snap_row.get(f)):
                raise domain_violation(
                    "snapshot_value",
                    f"Proposed {f} for {oid} does not equal the approved snapshot value; values are resolved "
                    "from the snapshot, never supplied by the caller.",
                    order_id=oid, field=f, proposed=value, snapshot_value=snap_row.get(f),
                )

    # 2. current authority and state of each target
    assessed = q.assess_orders(conn, tenant_id, order_ids, snapshot)
    for oid in order_ids:
        a = assessed[oid]
        if a.condition == "deleted_tombstoned":
            raise domain_violation(
                "tombstone",
                f"Order {oid} (or its customer) was deleted after the snapshot; restoring it would resurrect "
                "deleted data.",
                order_id=oid, tombstone=_tomb_evidence(a.tombstone),
            )
        if a.condition == "on_hold":
            raise domain_violation(
                "record_hold",
                f"Order {oid} is under an active hold ({a.hold['reason']}).",  # type: ignore[index]
                order_id=oid, hold_id=a.hold["hold_id"],  # type: ignore[index]
            )
        if a.current_row is None:
            raise domain_violation(
                "missing_row", f"Order {oid} no longer exists and has no tombstone; refusing to re-create it.",
                order_id=oid,
            )
        if a.condition == "changed_after_snapshot":
            raise domain_violation(
                "later_update",
                f"Order {oid} was updated after the snapshot by {a.current_row['updated_by']}; "
                "repairing it would overwrite a legitimate later change.",
                order_id=oid, updated_by=a.current_row["updated_by"], updated_at=fx.iso(a.current_row["updated_at"]),
            )

    # 3. build exact cell changes, only where current differs from the snapshot
    changes: list[ManifestChange] = []
    for r in sorted(repairs, key=lambda x: x["order_id"]):
        oid = r["order_id"]
        a = assessed[oid]
        fields = sorted(set(r["fields"]) | set(r.get("proposed_values") or {}))
        for f in fields:
            snap_value = a.snapshot_row.get(f)
            cur_value = a.current_row.get(f)  # type: ignore[union-attr]
            if values_equal(snap_value, cur_value):
                continue
            changes.append(
                ManifestChange(
                    entity="order",
                    row_id=oid,
                    field=f,
                    op="update",
                    current_value=cur_value,
                    new_value=snap_value,
                    source_path=f"snapshot:{snapshot_id}/orders/{oid}/{f}",
                )
            )
    if not changes:
        raise domain_violation(
            "nothing_to_repair", "The requested orders already match the approved snapshot on the requested fields."
        )

    target_ids = sorted({c.row_id for c in changes})
    restored = sum(
        max(0, int(c.new_value) - int(c.current_value))
        for c in changes
        if c.field == "total_cents" and c.new_value is not None and c.current_value is not None
    )
    reviewable = set(grant.reviewable.get("order", []))
    review_reasons: list[str] = []
    flagged = sorted(set(target_ids) & reviewable)
    if flagged:
        review_reasons.append(f"{', '.join(flagged)} {'is' if len(flagged) == 1 else 'are'} marked for second review")
    if restored > grant.limits.review_threshold_cents:
        review_reasons.append(
            f"restores ${restored / 100:,.2f}, above the ${grant.limits.review_threshold_cents / 100:,.2f} review threshold"
        )
    requires_review = bool(review_reasons)

    preconditions = ManifestPreconditions(
        authority_epoch=epoch,
        row_versions={oid: int(assessed[oid].current_row["row_version"]) for oid in target_ids},  # type: ignore[index]
        fixture_generation=generation,
        tombstone_free=sorted(
            [f"order:{oid}" for oid in target_ids]
            + [f"customer:{assessed[oid].customer_id}" for oid in target_ids]
        ),
        hold_free=[f"order:{oid}" for oid in target_ids],
    )

    manifest = ExecutionManifest(
        manifest_id=new_id("mf"),
        grant_id=grant.grant_id,
        run_id=run_id,
        principal=grant.principal,
        tenant_id=tenant_id,
        workflow=grant.workflow,
        snapshot_id=snapshot_id,
        snapshot_digest=snapshot["content_digest"],
        changes=changes,
        preconditions=preconditions,
        restored_value_cents=restored,
        requires_review=requires_review,
        review_reason="; ".join(review_reasons) if review_reasons else None,
        content_digest="sha256:pending",
        status="prepared",
        created_at=utcnow(),
    )
    return manifest.model_copy(update={"content_digest": compute_content_digest(manifest)})


def _tomb_evidence(tomb: dict[str, Any] | None) -> dict[str, Any]:
    if not tomb:
        return {}
    return {
        "entity_type": tomb["entity_type"],
        "entity_id": tomb["entity_id"],
        "deleted_at": fx.iso(tomb["deleted_at"]),
        "reason": tomb["reason"],
    }


def build_manifest(
    conn: psycopg.Connection,
    grant: TaskGrant,
    args: dict[str, Any],
    run_id: str,
    *,
    proposal_id: str | None = None,
) -> ExecutionManifest | Decision:
    """Resolve ``args`` into an ``ExecutionManifest`` (not persisted) or a blocking ``Decision``."""
    try:
        return plan_manifest(conn, grant, args, run_id)
    except Violation as v:
        return v.to_decision(run_id, proposal_id)


def store_manifest(conn: psycopg.Connection, manifest: ExecutionManifest) -> None:
    q.cursor(conn).execute(
        "INSERT INTO runtime.manifests (manifest_id, grant_id, run_id, tenant_id, body, content_digest, status, "
        "fixture_generation) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            manifest.manifest_id,
            manifest.grant_id,
            manifest.run_id,
            manifest.tenant_id,
            Jsonb(manifest.model_dump(mode="json")),
            manifest.content_digest,
            manifest.status,
            manifest.preconditions.fixture_generation,
        ),
    )


def prepare_manifest(
    conn: psycopg.Connection,
    grant: TaskGrant,
    args: dict[str, Any],
    run_id: str,
    *,
    proposal_id: str | None = None,
) -> ExecutionManifest | Decision:
    """Build a manifest and, when it is valid, persist it (immutable) in one transaction."""
    with conn.transaction():
        result = build_manifest(conn, grant, args, run_id, proposal_id=proposal_id)
        if isinstance(result, ExecutionManifest):
            store_manifest(conn, result)
    return result


def load_manifest(
    conn: psycopg.Connection, manifest_id: str, *, for_update: bool = False
) -> ExecutionManifest | None:
    """Load a stored manifest. The ``status`` column is authoritative (the body copy is immutable)."""
    row = q.cursor(conn).execute(
        "SELECT body, status FROM runtime.manifests WHERE manifest_id = %s" + (" FOR UPDATE" if for_update else ""),
        (manifest_id,),
    ).fetchone()
    if row is None:
        return None
    manifest = ExecutionManifest.model_validate(row["body"])
    return manifest.model_copy(update={"status": row["status"]})


def mark_manifest_status(conn: psycopg.Connection, manifest_id: str, status: str, *, only_if: str = "prepared") -> None:
    with conn.transaction():
        q.cursor(conn).execute(
            "UPDATE runtime.manifests SET status = %s WHERE manifest_id = %s AND status = %s",
            (status, manifest_id, only_if),
        )


def preview_diff(manifest: ExecutionManifest) -> list[dict[str, Any]]:
    """Cell-level preview shown to the agent, the reviewer and the UI."""
    return [
        {
            "order_id": c.row_id,
            "field": c.field,
            "current_value": c.current_value,
            "new_value": c.new_value,
            "source": c.source_path,
        }
        for c in manifest.changes
    ]
