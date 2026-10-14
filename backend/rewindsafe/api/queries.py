"""Read-only SQL used by the HTTP layer (run detail, listings, snapshot diff).

Writes never happen here: all effects go through the dispatcher/adapter.
"""

from __future__ import annotations

from typing import Any

from rewindsafe.contracts import (
    ActionProposal,
    ApprovalRecord,
    Decision,
    ExecutionManifest,
    ExecutionReceipt,
    Run,
)
from rewindsafe.runtime import db

_RUN_SELECT = """
    SELECT r.run_id, r.grant_id, r.scenario_id, r.workflow, r.planner, r.planner_kind,
           r.enforcement_mode, r.status, r.outcome_summary, r.steps_used, r.replans_used,
           r.plan, r.fixture_generation, r.created_by, r.created_at, r.updated_at,
           r.finished_at, r.metadata, g.tenant_id AS tenant_id
    FROM runtime.runs r JOIN runtime.task_grants g ON g.grant_id = r.grant_id
"""


def _to_run(row: dict[str, Any]) -> tuple[Run, str]:
    data = dict(row)
    tenant_id = data.pop("tenant_id")
    return Run.model_validate(data), tenant_id


def get_run_with_tenant(run_id: str) -> tuple[Run, str] | None:
    with db.connection() as conn:
        row = conn.execute(_RUN_SELECT + " WHERE r.run_id = %s", (run_id,)).fetchone()
    return _to_run(row) if row else None


def list_runs_for_tenant(tenant_id: str, limit: int = 30) -> list[Run]:
    with db.connection() as conn:
        rows = conn.execute(
            _RUN_SELECT + " WHERE g.tenant_id = %s ORDER BY r.created_at DESC LIMIT %s",
            (tenant_id, limit),
        ).fetchall()
    return [_to_run(r)[0] for r in rows]


def finished_seq(run_id: str) -> int | None:
    """Sequence number of the run.finished event, if the run has ended."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT max(seq) AS seq FROM runtime.events WHERE run_id = %s AND event_type = 'run.finished'",
            (run_id,),
        ).fetchone()
    return row["seq"] if row and row["seq"] is not None else None


def approval_tenant(approval_id: str) -> str | None:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT tenant_id FROM runtime.approvals WHERE approval_id = %s", (approval_id,)
        ).fetchone()
    return row["tenant_id"] if row else None


def _manifest_with_status(row: dict[str, Any]) -> dict[str, Any]:
    body = dict(row["body"])
    body["status"] = row["status"]  # the column is authoritative; the body is immutable
    return body


def _approval_with_columns(row: dict[str, Any]) -> dict[str, Any]:
    body = dict(row["body"])
    body["status"] = row["status"]
    if row.get("decided_by"):
        body["decided_by"] = row["decided_by"]
    if row.get("decided_at"):
        body["decided_at"] = row["decided_at"]
    return body


def manifest_body(manifest_id: str | None) -> dict[str, Any] | None:
    if not manifest_id:
        return None
    with db.connection() as conn:
        row = conn.execute(
            "SELECT body, status FROM runtime.manifests WHERE manifest_id = %s", (manifest_id,)
        ).fetchone()
    return _manifest_with_status(row) if row else None


def run_rows(run_id: str) -> dict[str, list[Any]]:
    """Raw rows needed to assemble a RunDetail for ``run_id``."""
    with db.connection() as conn:
        proposals = conn.execute(
            "SELECT proposal_id, run_id, step_index, tool, arguments, rationale, source, status, created_at "
            "FROM runtime.proposals WHERE run_id = %s ORDER BY step_index, created_at",
            (run_id,),
        ).fetchall()
        decisions = conn.execute(
            "SELECT body FROM runtime.decisions WHERE run_id = %s ORDER BY created_at, decision_id",
            (run_id,),
        ).fetchall()
        manifests = conn.execute(
            "SELECT body, status FROM runtime.manifests WHERE run_id = %s ORDER BY created_at", (run_id,)
        ).fetchall()
        receipts = conn.execute(
            "SELECT body FROM runtime.receipts WHERE run_id = %s ORDER BY created_at", (run_id,)
        ).fetchall()
        approvals = conn.execute(
            "SELECT body, status, decided_by, decided_at FROM runtime.approvals WHERE run_id = %s "
            "ORDER BY requested_at",
            (run_id,),
        ).fetchall()
        prepared = conn.execute(
            "SELECT body FROM runtime.events WHERE run_id = %s AND event_type = 'manifest.prepared' "
            "ORDER BY seq",
            (run_id,),
        ).fetchall()
    return {
        "proposals": proposals,
        "decisions": [r["body"] for r in decisions],
        "manifests": [_manifest_with_status(r) for r in manifests],
        "receipts": [r["body"] for r in receipts],
        "approvals": [_approval_with_columns(r) for r in approvals],
        "prepared_events": [r["body"] for r in prepared],
    }


def assemble_run_detail(run: Run, grant: Any, rows: dict[str, list[Any]]) -> dict[str, Any]:
    """Pure assembly of the proposal -> decisions/manifest/receipt/approval links."""
    manifests = {m["manifest_id"]: m for m in rows["manifests"]}

    # manifest.prepared events carry the proposal that produced the manifest.
    prepared_by_proposal: dict[str, str] = {}
    for ev in rows["prepared_events"]:
        pid = ev.get("proposal_id")
        mid = ((ev.get("data") or {}).get("manifest") or {}).get("manifest_id")
        if pid and mid:
            prepared_by_proposal[pid] = mid

    decisions_by_proposal: dict[str, list[dict[str, Any]]] = {}
    for d in rows["decisions"]:
        decisions_by_proposal.setdefault(d.get("proposal_id") or "", []).append(d)
    approvals_by_proposal = {a["proposal_id"]: a for a in rows["approvals"]}

    items: list[dict[str, Any]] = []
    for prow in rows["proposals"]:
        proposal = ActionProposal.model_validate(prow)
        args = proposal.arguments or {}
        manifest_id: str | None = None
        receipt: dict[str, Any] | None = None
        if proposal.tool == "apply_repair_manifest":
            manifest_id = args.get("manifest_id")
            matching = [r for r in rows["receipts"] if r.get("manifest_id") == manifest_id]
            exact = [r for r in matching if r.get("idempotency_key") == args.get("idempotency_key")]
            receipt = (exact or matching or [None])[0]
        elif proposal.tool == "prepare_repair_manifest":
            manifest_id = prepared_by_proposal.get(proposal.proposal_id)
        manifest = manifests.get(manifest_id) if manifest_id else None
        approval = approvals_by_proposal.get(proposal.proposal_id)
        items.append(
            {
                "proposal": proposal.model_dump(mode="json"),
                "decisions": [
                    Decision.model_validate(d).model_dump(mode="json")
                    for d in decisions_by_proposal.get(proposal.proposal_id, [])
                ],
                "manifest": ExecutionManifest.model_validate(manifest).model_dump(mode="json")
                if manifest
                else None,
                "receipt": ExecutionReceipt.model_validate(receipt).model_dump(mode="json") if receipt else None,
                "approval": ApprovalRecord.model_validate(approval).model_dump(mode="json") if approval else None,
            }
        )

    return {
        "run": run.model_dump(mode="json"),
        "grant": grant.model_dump(mode="json"),
        "proposals": items,
        "approvals": [ApprovalRecord.model_validate(a).model_dump(mode="json") for a in rows["approvals"]],
        "receipts": [ExecutionReceipt.model_validate(r).model_dump(mode="json") for r in rows["receipts"]],
    }


# ─── snapshot diff (used when the adapter has no snapshot_diff hook) ───────

_DIFF_FIELDS = ("status", "total_cents", "shipping_region")


def classify_order(
    snapshot: dict[str, Any],
    current: dict[str, Any] | None,
    *,
    on_hold: bool,
) -> tuple[str, list[str]]:
    """Return (condition, differing_fields) for one order."""
    if current is None:
        return "deleted_tombstoned", list(_DIFF_FIELDS)
    differing = [f for f in _DIFF_FIELDS if current.get(f) != snapshot.get(f)]
    if on_hold and differing:
        return "on_hold", differing
    if not differing:
        return "healthy", []
    if str(current.get("updated_by", "")).startswith("migration:"):
        return "damaged", differing
    return "changed_after_snapshot", differing


def snapshot_diff_for_tenant(tenant_id: str) -> list[dict[str, Any]]:
    """Per-order comparison of the approved snapshot with current state for one tenant."""
    with db.connection() as conn:
        snap = conn.execute(
            "SELECT content FROM recovery.snapshots WHERE approved ORDER BY taken_at DESC LIMIT 1"
        ).fetchone()
        current = {
            r["order_id"]: r
            for r in conn.execute(
                "SELECT order_id, status, total_cents, shipping_region, updated_by "
                "FROM app.orders WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchall()
        }
        held = {
            r["entity_id"]
            for r in conn.execute(
                "SELECT entity_id FROM authority.record_holds "
                "WHERE tenant_id = %s AND entity_type = 'order' AND active",
                (tenant_id,),
            ).fetchall()
        }
    if not snap:
        return []
    content = snap["content"]
    customers = {c["customer_id"]: c.get("name", "") for c in content.get("customers", [])}
    rows: list[dict[str, Any]] = []
    for order in sorted(content.get("orders", []), key=lambda o: o["order_id"]):
        if order.get("tenant_id") != tenant_id:
            continue
        oid = order["order_id"]
        snap_vals = {f: order.get(f) for f in _DIFF_FIELDS}
        cur = current.get(oid)
        condition, differing = classify_order(snap_vals, cur, on_hold=oid in held)
        rows.append(
            {
                "order_id": oid,
                "customer_name": customers.get(order.get("customer_id"), ""),
                "condition": condition,
                "snapshot": snap_vals,
                "current": {f: cur[f] for f in _DIFF_FIELDS} if cur else None,
                "differing_fields": differing,
            }
        )
    return rows
