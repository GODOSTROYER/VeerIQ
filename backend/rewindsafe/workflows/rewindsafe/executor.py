"""The sole executor of application-data mutations: transactional, idempotent, least-privilege.

Lock order (every writer of authority or runtime state obeys it; see also
``authority_admin``):

1. ``runtime.fixture_state``   FOR SHARE   (generation must equal the manifest's)
2. ``runtime.task_grants`` row FOR UPDATE  (active, unexpired, commits_used < max_commits)
3. ``runtime.manifests`` row   FOR UPDATE  (must still be ``prepared``)
4. ``authority.tenant_epochs`` FOR SHARE   (epoch must equal the preview's)
5. ``app.orders`` target rows  FOR UPDATE ORDER BY order_id

Authority writers take (1) FOR SHARE, then (4) FOR UPDATE, and never lock grants,
manifests or orders. Resets take (1) FOR UPDATE. Because every apply for a grant
serializes on (2), the idempotency check made under that lock is authoritative and
the ``UNIQUE (grant_id, idempotency_key)`` constraint is a second line of defense.

All data writes run under ``SET LOCAL ROLE rs_executor``, which PostgreSQL limits to
column-level UPDATE on the repairable order columns (row-level security pins it to the
manifest's tenant via ``rewindsafe.tenant``), INSERT-only receipts, no write access to
approvals or ``authority.*``, and column-level UPDATE of only commits_used/status/body on
grants (migration 002).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg import errors as pg_errors
from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from rewindsafe.contracts import (
    ApprovalRecord,
    Decision,
    DecisionSource,
    DispatchStatus,
    ExecutionManifest,
    ExecutionReceipt,
    InvariantStatus,
    Layer,
    Outcome,
    ReceiptChange,
    TaskGrant,
)
from rewindsafe.runtime.canonical import digest, new_id, utcnow
from rewindsafe.workflows.rewindsafe import fixture as fx
from rewindsafe.workflows.rewindsafe import queries as q
from rewindsafe.workflows.rewindsafe.manifest import (
    approval_payload_digest,
    load_manifest,
    make_decision,
    manifest_integrity_ok,
    mark_manifest_status,
    preview_diff,
)

HANDLER = "apply_repair_manifest"
_ALLOWED_COLUMNS = frozenset(fx.REPAIRABLE_FIELDS)


@dataclass
class ApplyResult:
    """Outcome of one apply attempt. ``kind`` is one of committed / duplicate / rejected."""

    status: DispatchStatus
    kind: str
    summary: str
    observation: dict[str, Any]
    decisions: list[Decision] = field(default_factory=list)
    receipt: ExecutionReceipt | None = None
    manifest: ExecutionManifest | None = None
    state_changed: bool = False


class _Abort(Exception):
    """Raised inside the transaction to roll it back and carry the rejection out."""

    def __init__(self, result: ApplyResult, *, mark_stale: bool = False) -> None:
        super().__init__(result.summary)
        self.result = result
        self.mark_stale = mark_stale


# ─── receipts / idempotency ────────────────────────────────────────────────


def lookup_receipt(conn: psycopg.Connection, grant_id: str, idempotency_key: str) -> ExecutionReceipt | None:
    row = q.cursor(conn).execute(
        "SELECT body FROM runtime.receipts WHERE grant_id = %s AND idempotency_key = %s",
        (grant_id, idempotency_key),
    ).fetchone()
    return ExecutionReceipt.model_validate(row["body"]) if row else None


def check_idempotency(
    conn: psycopg.Connection, grant_id: str, idempotency_key: str, requested_digest: str
) -> tuple[str, ExecutionReceipt | None]:
    """Returns ``("none"|"duplicate"|"conflict", receipt)`` for this (grant, key, payload digest)."""
    receipt = lookup_receipt(conn, grant_id, idempotency_key)
    if receipt is None:
        return "none", None
    if receipt.manifest_digest == requested_digest:
        return "duplicate", receipt
    return "conflict", receipt


def receipt_by_operation(conn: psycopg.Connection, operation_id: str) -> ExecutionReceipt | None:
    row = q.cursor(conn).execute("SELECT body FROM runtime.receipts WHERE operation_id = %s", (operation_id,)).fetchone()
    return ExecutionReceipt.model_validate(row["body"]) if row else None


def receipt_by_manifest(conn: psycopg.Connection, manifest_id: str) -> ExecutionReceipt | None:
    row = q.cursor(conn).execute(
        "SELECT body FROM runtime.receipts WHERE manifest_id = %s ORDER BY created_at DESC LIMIT 1", (manifest_id,)
    ).fetchone()
    return ExecutionReceipt.model_validate(row["body"]) if row else None


def latest_receipt_for_grant(conn: psycopg.Connection, grant_id: str) -> ExecutionReceipt | None:
    row = q.cursor(conn).execute(
        "SELECT body FROM runtime.receipts WHERE grant_id = %s ORDER BY created_at DESC LIMIT 1", (grant_id,)
    ).fetchone()
    return ExecutionReceipt.model_validate(row["body"]) if row else None


def receipt_observation(receipt: ExecutionReceipt) -> dict[str, Any]:
    return receipt.model_dump(mode="json")


def _duplicate_result(receipt: ExecutionReceipt, manifest: ExecutionManifest | None) -> ApplyResult:
    return ApplyResult(
        status=DispatchStatus.DUPLICATE,
        kind="duplicate",
        summary=f"Idempotent replay: returned original receipt {receipt.operation_id}; nothing was changed again.",
        observation={
            "status": "duplicate",
            "message": "This idempotency key was already used for this exact manifest. The original receipt is "
            "returned and no data was changed.",
            "operation_id": receipt.operation_id,
            "receipt": receipt_observation(receipt),
        },
        receipt=receipt,
        manifest=manifest,
        state_changed=False,
    )


def _conflict_result(run_id: str, key: str, receipt: ExecutionReceipt) -> ApplyResult:
    reason = (
        f"Idempotency key {key!r} was already used for a different payload "
        f"(recorded digest {receipt.manifest_digest[:19]}...). A key identifies exactly one request."
    )
    return ApplyResult(
        status=DispatchStatus.BLOCKED,
        kind="rejected",
        summary="Idempotency key reused with a different payload; nothing was changed.",
        observation={"status": "blocked", "blocked_by": DecisionSource.DOMAIN.value, "reason": reason},
        decisions=[
            make_decision(
                run_id, Layer.DOMAIN, DecisionSource.DOMAIN, Outcome.BLOCK, reason,
                invariant="idempotency_conflict",
                evidence={"idempotency_key": key, "recorded_operation_id": receipt.operation_id},
            )
        ],
    )


def _blocked(
    run_id: str,
    layer: Layer,
    source: DecisionSource,
    invariant: str,
    reason: str,
    summary: str,
    manifest: ExecutionManifest | None = None,
    **evidence: Any,
) -> ApplyResult:
    return ApplyResult(
        status=DispatchStatus.BLOCKED,
        kind="rejected",
        summary=summary,
        observation={"status": "blocked", "blocked_by": source.value, "reason": reason},
        decisions=[make_decision(run_id, layer, source, Outcome.BLOCK, reason, invariant=invariant, evidence=evidence)],
        manifest=manifest,
    )


def _stale(
    run_id: str,
    layer: Layer,
    source: DecisionSource,
    invariant: str,
    reason: str,
    manifest: ExecutionManifest,
    **evidence: Any,
) -> ApplyResult:
    return ApplyResult(
        status=DispatchStatus.STALE,
        kind="rejected",
        summary=f"Rejected as stale, no changes made: {reason}",
        observation={
            "status": "stale",
            "reason": reason,
            "guidance": "Authority or data changed after the preview. Nothing was changed. Re-inspect the current "
            "state and prepare a new manifest for whatever is still within your grant.",
        },
        decisions=[make_decision(run_id, layer, source, Outcome.BLOCK, reason, invariant=invariant, evidence=evidence)],
        manifest=manifest,
    )


# ─── apply ─────────────────────────────────────────────────────────────────


def apply_manifest_tx(
    conn: psycopg.Connection,
    grant: TaskGrant,
    manifest: ExecutionManifest,
    idempotency_key: str,
    approval: ApprovalRecord | None,
    run_id: str,
    *,
    requested_digest: str | None = None,
    enforcement_mode: str = "offline",
    sdk_version: str | None = None,
) -> ApplyResult:
    """Apply ``manifest`` atomically. Never raises for an expected rejection; returns an ``ApplyResult``.

    ``conn`` must be idle (no open transaction): this function owns the transaction so
    that its locks and ``SET LOCAL ROLE`` have the documented scope.
    ``requested_digest`` is the digest the caller named in the request (defaults to the
    manifest's own); it is what the idempotency key is bound to.
    """
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise RuntimeError("apply_manifest_tx needs an idle connection; it opens and owns the transaction")
    requested = requested_digest or manifest.content_digest

    # Fast path: idempotent replay. Deliberately no stale-version check here.
    with conn.transaction():
        outcome, prior = check_idempotency(conn, grant.grant_id, idempotency_key, requested)
    if outcome == "duplicate":
        return _duplicate_result(prior, manifest)  # type: ignore[arg-type]
    if outcome == "conflict":
        return _conflict_result(run_id, idempotency_key, prior)  # type: ignore[arg-type]
    if requested != manifest.content_digest:
        return _blocked(
            run_id, Layer.DOMAIN, DecisionSource.DOMAIN, "manifest_digest",
            "The digest supplied does not match the stored manifest.", "Manifest digest mismatch; nothing changed.",
            manifest, supplied=requested, stored=manifest.content_digest,
        )

    try:
        with conn.transaction():
            return _apply_locked(conn, grant, manifest, idempotency_key, approval, run_id, enforcement_mode, sdk_version)
    except _Abort as abort:
        if abort.mark_stale:
            mark_manifest_status(conn, manifest.manifest_id, "stale")
            abort.result.manifest = abort.result.manifest.model_copy(update={"status": "stale"}) if abort.result.manifest else None
        return abort.result
    except pg_errors.InsufficientPrivilege as exc:
        reason = (
            "PostgreSQL refused the write: the executor role has no privilege for it "
            f"({_short(exc)}). The transaction was rolled back."
        )
        return _blocked(
            run_id, Layer.POSTGRES, DecisionSource.PG_PRIVILEGE, "pg_privilege", reason,
            "PostgreSQL privilege check refused the write; nothing changed.", manifest,
        )


def _short(exc: BaseException) -> str:
    return str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__


def _apply_locked(
    conn: psycopg.Connection,
    grant: TaskGrant,
    manifest: ExecutionManifest,
    key: str,
    approval: ApprovalRecord | None,
    run_id: str,
    enforcement_mode: str,
    sdk_version: str | None,
) -> ApplyResult:
    cur = q.cursor(conn)
    pre = manifest.preconditions

    # 1. fixture generation
    gen_row = cur.execute("SELECT generation FROM runtime.fixture_state WHERE id = 1 FOR SHARE").fetchone()
    generation = int(gen_row["generation"]) if gen_row else -1
    if generation != pre.fixture_generation:
        raise _Abort(
            _stale(
                run_id, Layer.DOMAIN, DecisionSource.DOMAIN, "generation",
                f"The demo was reset after this manifest was prepared (generation {pre.fixture_generation} -> {generation}).",
                manifest, manifest_generation=pre.fixture_generation, current_generation=generation,
            ),
            mark_stale=True,
        )

    # 2. grant row
    grow = cur.execute(
        "SELECT status, commits_used, max_commits, expires_at, tenant_id, fixture_generation "
        "FROM runtime.task_grants WHERE grant_id = %s FOR UPDATE",
        (grant.grant_id,),
    ).fetchone()
    if grow is None:
        raise _Abort(_blocked(run_id, Layer.RUNTIME, DecisionSource.LIFECYCLE, "grant_inactive",
                              "The task grant does not exist.", "Grant missing; nothing changed.", manifest))
    # The earlier idempotency read was outside this lock; re-check under it (a racing apply may have just committed).
    outcome, prior = check_idempotency(conn, grant.grant_id, key, manifest.content_digest)
    if outcome == "duplicate":
        raise _Abort(_duplicate_result(prior, manifest))  # type: ignore[arg-type]
    if outcome == "conflict":
        raise _Abort(_conflict_result(run_id, key, prior))  # type: ignore[arg-type]

    now = utcnow()
    if grow["status"] != "active":
        invariant = "grant_exhausted" if grow["status"] == "exhausted" else "grant_inactive"
        raise _Abort(_blocked(
            run_id, Layer.RUNTIME, DecisionSource.LIFECYCLE, invariant,
            f"The task grant is {grow['status']}, so no further commit is allowed.",
            "Grant is not active; nothing changed.", manifest, status=grow["status"],
        ))
    if grow["expires_at"] <= now:
        raise _Abort(_blocked(
            run_id, Layer.RUNTIME, DecisionSource.LIFECYCLE, "grant_expired",
            "The task grant has expired.", "Grant expired; nothing changed.", manifest,
        ))
    if int(grow["commits_used"]) >= int(grow["max_commits"]):
        raise _Abort(_blocked(
            run_id, Layer.RUNTIME, DecisionSource.LIFECYCLE, "grant_exhausted",
            f"The grant's commit budget ({grow['max_commits']}) is used up.", "Commit budget exhausted; nothing changed.",
            manifest, commits_used=int(grow["commits_used"]), max_commits=int(grow["max_commits"]),
        ))
    if grow["tenant_id"] != manifest.tenant_id or manifest.grant_id != grant.grant_id:
        raise _Abort(_blocked(
            run_id, Layer.GRANT, DecisionSource.GRANT_SCOPE, "manifest_scope",
            "The manifest does not belong to this grant and tenant.", "Manifest outside grant scope; nothing changed.", manifest,
        ))

    # 3. manifest row: still prepared and unmodified
    locked = load_manifest(conn, manifest.manifest_id, for_update=True)
    if locked is None or locked.status != "prepared":
        status = locked.status if locked else "missing"
        raise _Abort(_blocked(
            run_id, Layer.DOMAIN, DecisionSource.DOMAIN, "manifest_digest",
            f"The manifest is {status}, not prepared; it cannot be applied.", f"Manifest is {status}; nothing changed.",
            locked or manifest, manifest_status=status,
        ))
    if locked.content_digest != manifest.content_digest or not manifest_integrity_ok(locked):
        raise _Abort(_blocked(
            run_id, Layer.DOMAIN, DecisionSource.DOMAIN, "manifest_digest",
            "The stored manifest content does not match its digest.", "Manifest integrity check failed; nothing changed.",
            locked,
        ))
    manifest = locked

    snap = q.load_snapshot(conn, manifest.snapshot_id)
    if snap is None or snap["content_digest"] != manifest.snapshot_digest:
        raise _Abort(_blocked(
            run_id, Layer.DOMAIN, DecisionSource.DOMAIN, "snapshot_value",
            "The approved snapshot no longer matches the digest the manifest was prepared from.",
            "Snapshot digest changed; nothing changed.", manifest,
        ))

    # 4. authority epoch
    erow = cur.execute(
        "SELECT epoch FROM authority.tenant_epochs WHERE tenant_id = %s FOR SHARE", (manifest.tenant_id,)
    ).fetchone()
    epoch = int(erow["epoch"]) if erow else -1
    target_ids = sorted({c.row_id for c in manifest.changes})
    if epoch != pre.authority_epoch:
        raise _Abort(
            _stale(
                run_id, Layer.POSTGRES, DecisionSource.PG_TRANSACTION, "stale_epoch",
                _describe_authority_change(conn, manifest, pre.authority_epoch, epoch),
                manifest, preview_epoch=pre.authority_epoch, current_epoch=epoch,
            ),
            mark_stale=True,
        )

    # 5. target rows
    rows = cur.execute(
        f"SELECT {q.ORDER_COLUMNS} FROM app.orders WHERE order_id = ANY(%s) ORDER BY order_id FOR UPDATE",
        (target_ids,),
    ).fetchall()
    current = {r["order_id"]: r for r in rows}
    tombs = q.fetch_tombstones(conn, manifest.tenant_id)
    holds = q.fetch_active_holds(conn, manifest.tenant_id)
    snap_orders = q.snapshot_orders_by_id(snap)
    for oid in target_ids:
        row = current.get(oid)
        cust = snap_orders[oid]["customer_id"]
        if ("order", oid) in tombs or ("customer", cust) in tombs:
            raise _Abort(_stale(
                run_id, Layer.DOMAIN, DecisionSource.DOMAIN, "tombstone",
                f"Order {oid} was deleted after the preview; it will not be restored.", manifest, order_id=oid,
            ), mark_stale=True)
        hold = holds.get(("order", oid)) or holds.get(("customer", cust))
        if hold is not None:
            raise _Abort(_stale(
                run_id, Layer.DOMAIN, DecisionSource.DOMAIN, "record_hold",
                f"Order {oid} is under hold {hold['hold_id']} ({hold['reason']}).", manifest,
                order_id=oid, hold_id=hold["hold_id"],
            ), mark_stale=True)
        if row is None:
            raise _Abort(_stale(
                run_id, Layer.POSTGRES, DecisionSource.PG_TRANSACTION, "stale_row_version",
                f"Order {oid} no longer exists.", manifest, order_id=oid,
            ), mark_stale=True)
        if int(row["row_version"]) != int(pre.row_versions[oid]):
            raise _Abort(_stale(
                run_id, Layer.POSTGRES, DecisionSource.PG_TRANSACTION, "stale_row_version",
                f"Order {oid} changed after the preview (row version {pre.row_versions[oid]} -> {row['row_version']}, "
                f"last written by {row['updated_by']}).", manifest,
                order_id=oid, preview_version=pre.row_versions[oid], current_version=int(row["row_version"]),
            ), mark_stale=True)
        for c in (c for c in manifest.changes if c.row_id == oid):
            if c.field not in _ALLOWED_COLUMNS:
                raise _Abort(_blocked(
                    run_id, Layer.GRANT, DecisionSource.GRANT_SCOPE, "field_scope",
                    f"Field {c.field!r} is not repairable.", "Field outside scope; nothing changed.", manifest,
                ))
            if row[c.field] != c.current_value:
                raise _Abort(_stale(
                    run_id, Layer.POSTGRES, DecisionSource.PG_TRANSACTION, "stale_row_version",
                    f"{oid}.{c.field} no longer holds the value observed at preview.", manifest, order_id=oid, field=c.field,
                ), mark_stale=True)

    # 6. approval, bound to the exact payload
    approval_id: str | None = None
    if manifest.requires_review:
        approval_id = _check_approval(conn, run_id, grant, manifest, approval)

    # 7. write under least privilege
    # Row-level security on app.orders limits rs_executor to this tenant's rows (migration 002).
    cur.execute("SELECT set_config('rewindsafe.tenant', %s, true)", (manifest.tenant_id,))
    cur.execute("SET LOCAL ROLE rs_executor")
    updated_by = f"rewindsafe:{run_id}"
    now = utcnow()
    receipt_changes: list[ReceiptChange] = []
    for oid in target_ids:
        cell_changes = [c for c in manifest.changes if c.row_id == oid]
        assignments = [sql.SQL("{} = %s").format(sql.Identifier(c.field)) for c in cell_changes]
        params: list[Any] = [c.new_value for c in cell_changes]
        statement = sql.SQL(
            "UPDATE app.orders SET {sets}, row_version = row_version + 1, updated_at = %s, updated_by = %s "
            "WHERE order_id = %s AND tenant_id = %s AND row_version = %s"
        ).format(sets=sql.SQL(", ").join(assignments))
        cur.execute(statement, [*params, now, updated_by, oid, manifest.tenant_id, pre.row_versions[oid]])
        if cur.rowcount != 1:
            raise _Abort(_stale(
                run_id, Layer.POSTGRES, DecisionSource.PG_TRANSACTION, "stale_row_version",
                f"Order {oid} could not be updated at the previewed row version.", manifest, order_id=oid,
            ), mark_stale=True)
        for c in cell_changes:
            receipt_changes.append(ReceiptChange(row_id=oid, field=c.field, before=c.current_value, after=c.new_value))

    checks = q.protected_check_list(conn, manifest.tenant_id)
    if any(c.status == InvariantStatus.VIOLATED for c in checks):
        violated = [c.check_id for c in checks if c.status == InvariantStatus.VIOLATED]
        raise _Abort(_blocked(
            run_id, Layer.DOMAIN, DecisionSource.DOMAIN, "protected_state",
            f"The commit would violate protected state ({', '.join(violated)}); rolled back.",
            "Protected-state check failed; rolled back.", manifest, violated=violated,
        ))

    prohibited = int(cur.execute(
        "SELECT count(*) AS n FROM runtime.mutator_entries WHERE handler = 'restore_access_grant' AND run_id = %s",
        (run_id,),
    ).fetchone()["n"])  # type: ignore[index]

    sources = [DecisionSource.DOMAIN.value, DecisionSource.PG_TRANSACTION.value, DecisionSource.PG_PRIVILEGE.value]
    if approval_id:
        sources.append(DecisionSource.APPROVAL.value)
    receipt = ExecutionReceipt(
        operation_id=new_id("op"),
        idempotency_key=key,
        grant_id=grant.grant_id,
        run_id=run_id,
        manifest_id=manifest.manifest_id,
        manifest_digest=manifest.content_digest,
        result="committed",
        changes=receipt_changes,
        checks=checks,
        effect_counts={
            "rows_updated": len(target_ids),
            "cells_updated": len(receipt_changes),
            "prohibited_handler_entries": prohibited,
            "commits": 1,
        },
        decision_sources=sources,
        enforcement_mode="live" if enforcement_mode == "live" else "offline",
        sdk_version=sdk_version,
        fixture_generation=generation,
        approval_id=approval_id,
        created_at=now,
        committed_at=now,
        receipt_digest="sha256:pending",
    )
    receipt = receipt.model_copy(
        update={"receipt_digest": digest(receipt.model_dump(mode="json", exclude={"receipt_digest"}))}
    )

    inserted = cur.execute(
        "INSERT INTO runtime.receipts (operation_id, grant_id, idempotency_key, run_id, manifest_id, manifest_digest, "
        "result, body, receipt_digest, fixture_generation) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (grant_id, idempotency_key) DO NOTHING RETURNING operation_id",
        (
            receipt.operation_id, grant.grant_id, key, run_id, manifest.manifest_id, manifest.content_digest,
            receipt.result, Jsonb(receipt.model_dump(mode="json")), receipt.receipt_digest, generation,
        ),
    ).fetchone()
    if inserted is None:  # lost a race on the unique key: replay the winner's receipt
        cur.execute("RESET ROLE")
        winner = lookup_receipt(conn, grant.grant_id, key)
        if winner is not None and winner.manifest_digest == manifest.content_digest:
            raise _Abort(_duplicate_result(winner, manifest))
        raise _Abort(_conflict_result(run_id, key, winner))  # type: ignore[arg-type]

    new_commits = int(grow["commits_used"]) + 1
    new_status = "exhausted" if new_commits >= int(grow["max_commits"]) else "active"
    cur.execute(
        "UPDATE runtime.task_grants SET commits_used = %s, status = %s, "
        "body = body || jsonb_build_object('commits_used', %s::int, 'status', %s::text) WHERE grant_id = %s",
        (new_commits, new_status, new_commits, new_status, grant.grant_id),
    )
    cur.execute("UPDATE runtime.manifests SET status = 'committed' WHERE manifest_id = %s", (manifest.manifest_id,))
    cur.execute("RESET ROLE")

    committed = manifest.model_copy(update={"status": "committed"})
    return ApplyResult(
        status=DispatchStatus.EXECUTED,
        kind="committed",
        summary=(
            f"Committed {len(receipt_changes)} cell change(s) across {len(target_ids)} order(s) "
            f"({', '.join(target_ids)}); receipt {receipt.operation_id}."
        ),
        observation={
            "status": "committed",
            "operation_id": receipt.operation_id,
            "receipt": receipt_observation(receipt),
            "applied": preview_diff(committed),
            "commits_used": new_commits,
            "max_commits": int(grow["max_commits"]),
        },
        receipt=receipt,
        manifest=committed,
        state_changed=True,
    )


def _check_approval(
    conn: psycopg.Connection,
    run_id: str,
    grant: TaskGrant,
    manifest: ExecutionManifest,
    approval: ApprovalRecord | None,
) -> str:
    """Re-verify the approval against the database row (never trust the in-memory copy)."""
    def reject(invariant: str, reason: str, **evidence: Any) -> _Abort:
        return _Abort(_blocked(
            run_id, Layer.APPROVAL, DecisionSource.APPROVAL, invariant, reason,
            "Approval requirement not met; nothing changed.", manifest, **evidence,
        ))

    if approval is None:
        raise reject("approval_required", "This manifest requires a second reviewer's approval before it can be applied.")
    row = q.cursor(conn).execute(
        "SELECT approval_id, grant_id, payload_digest, status, expires_at, body FROM runtime.approvals "
        "WHERE approval_id = %s",
        (approval.approval_id,),
    ).fetchone()
    if row is None:
        raise reject("approval_required", "The approval record does not exist.")
    if row["status"] != "approved":
        raise reject("approval_required", f"The approval is {row['status']}, not approved.", approval_status=row["status"])
    if row["expires_at"] <= utcnow():
        raise reject("approval_expired", "The approval has expired.")
    expected = approval_payload_digest(manifest)
    body = row["body"] or {}
    if (
        row["grant_id"] != grant.grant_id
        or row["payload_digest"] != expected
        or body.get("manifest_id") != manifest.manifest_id
    ):
        raise reject(
            "approval_mismatch",
            "The approval was granted for a different payload than the one being applied.",
            approved_digest=row["payload_digest"], payload_digest=expected,
        )
    return row["approval_id"]


def _describe_authority_change(conn: psycopg.Connection, manifest: ExecutionManifest, before: int, after: int) -> str:
    holds = q.fetch_active_holds(conn, manifest.tenant_id)
    tombs = q.fetch_tombstones(conn, manifest.tenant_id)
    targets = {c.row_id for c in manifest.changes}
    parts = []
    for (etype, eid), h in holds.items():
        if etype == "order" and eid in targets:
            parts.append(f"{h['placed_by']} placed hold {h['hold_id']} on {eid} after preview ({h['reason']})")
    for (etype, eid), t in tombs.items():
        if etype == "order" and eid in targets:
            parts.append(f"{eid} was deleted ({t['reason']})")
    detail = "; ".join(parts) if parts else "an authority decision (hold, deletion or access change) was recorded"
    return f"Authority epoch moved {before} -> {after}: {detail}."
