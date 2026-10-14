"""Evidence export and metrics (architecture.md 4.11).

Evidence never contains API keys, JWTs, raw intent tokens or session cookies: every
payload passes through :func:`rewindsafe.runtime.canonical.redact_secrets`. Metrics
count only what was recorded; nothing is estimated.
"""

from __future__ import annotations

import logging
import math
import subprocess
from functools import lru_cache
from typing import Any, Optional

from rewindsafe.config import REPO_ROOT
from rewindsafe.contracts import (
    CONTRACT_VERSION,
    ActionProposal,
    Decision,
    DecisionSource,
    InvariantStatus,
    Layer,
    Outcome,
    Run,
    TaskGrant,
    ToolKind,
)
from rewindsafe.runtime import db, events, grants
from rewindsafe.runtime.adapter import WorkflowAdapter, all_adapters, get_adapter
from rewindsafe.runtime.canonical import redact_secrets, to_jsonable, utcnow

log = logging.getLogger(__name__)

LAYER_KEYS = ("armoriq", "armoriq_simulated", "grant", "domain", "postgres", "approval", "runtime")


# ─── small helpers ────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def source_commit() -> str:
    """``git rev-parse HEAD`` of the repo, or ``"uncommitted"`` (no git / no commit)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        sha = out.stdout.strip()
        return sha if out.returncode == 0 and sha else "uncommitted"
    except (OSError, subprocess.SubprocessError):
        return "uncommitted"


def percentile(values: list[float], q: float) -> Optional[float]:
    """Linear-interpolated percentile (``q`` in 0..1) or ``None`` for no data."""
    if not values:
        return None
    vals = sorted(values)
    pos = (len(vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return round(vals[lo], 2)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (pos - lo), 2)


def _stats(values: list[float]) -> dict[str, Any]:
    return {"p50": percentile(values, 0.5), "p95": percentile(values, 0.95), "count": len(values)}


def _armoriq_split(decisions: list[Decision]) -> dict[str, Any]:
    """Separate ArmorIQ numbers by what they measure (never mix local, mint, enforce, simulated).

    * ``enforce``: live ArmorIQ ``check`` round trips (network, ~sub-second);
    * ``issuance``: live plan token issuance (network, seconds, once per run);
    * ``plan_binding``: local SDK plan-binding checks (no network, so no latency is reported);
    * ``simulated_count``: RewindSafe's offline simulation, never counted as ArmorIQ.
    """
    enforce: list[float] = []
    issuance: list[float] = []
    plan_binding = 0
    simulated = 0
    for d in decisions:
        if d.layer != Layer.ARMORIQ:
            continue
        if d.simulated or d.source == DecisionSource.ARMORIQ_SIMULATED:
            simulated += 1
        elif d.source == DecisionSource.ARMORIQ_PLAN_BINDING:
            plan_binding += 1
        elif d.source == DecisionSource.ARMORIQ_TOKEN_ISSUANCE:
            if d.latency_ms is not None:
                issuance.append(d.latency_ms)
        elif d.source == DecisionSource.ARMORIQ_ENFORCE and not d.shadow and d.latency_ms is not None:
            enforce.append(d.latency_ms)
    return {
        "enforce": _stats(enforce),
        "issuance": _stats(issuance),
        "plan_binding": {"count": plan_binding},
        "simulated_count": simulated,
    }


def _latency_summary(decisions: list[Decision]) -> dict[str, Any]:
    """Legacy shape: top-level p50/p95/count alias the live ``enforce`` stats only."""
    split = _armoriq_split(decisions)
    return {
        **split["enforce"],
        "enforce": split["enforce"],
        "issuance": split["issuance"],
        "plan_mint": split["issuance"],
        "plan_binding_local_count": split["plan_binding"]["count"],
        "simulated_count": split["simulated_count"],
    }


def _blocked_by_layer(decisions: list[Decision]) -> dict[str, int]:
    out = dict.fromkeys(LAYER_KEYS, 0)
    for d in decisions:
        if d.decisive and not d.shadow and d.outcome == Outcome.BLOCK:
            key = d.layer.value
            if d.layer == Layer.ARMORIQ and (d.simulated or d.source == DecisionSource.ARMORIQ_SIMULATED):
                key = "armoriq_simulated"
            out[key] += 1
    return out


def _admin_handlers() -> set[str]:
    names: set[str] = set()
    for adapter in all_adapters():
        names.update(s.name for s in adapter.tool_specs() if s.kind == ToolKind.ADMIN)
    return names


def _violated_checks(
    adapter: Optional[WorkflowAdapter], tenant_id: str
) -> tuple[list[dict[str, Any]], Optional[str]]:
    if adapter is None:
        return [], "no adapter registered for the grant's workflow"
    try:
        checks = adapter.protected_checks(tenant_id)
    except Exception as exc:  # noqa: BLE001 - evidence must still be exportable
        log.exception("protected_checks failed")
        return [], f"protected_checks failed: {type(exc).__name__}"
    return [to_jsonable(c) for c in checks], None


def _adapter_for(workflow: str) -> Optional[WorkflowAdapter]:
    try:
        return get_adapter(workflow)
    except KeyError:
        return None


def _load_run(conn: Any, run_id: str) -> Run:
    row = conn.execute("SELECT * FROM runtime.runs WHERE run_id = %s", (run_id,)).fetchone()
    if row is None:
        raise LookupError(f"run {run_id} not found")
    return Run.model_validate(dict(row))


# ─── metrics ──────────────────────────────────────────────────────────────


def _run_metrics(run: Run, conn: Any, violated: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    run_id = run.run_id
    decisions = [
        Decision.model_validate(r["body"])
        for r in conn.execute(
            "SELECT body FROM runtime.decisions WHERE run_id = %s ORDER BY created_at, decision_id", (run_id,)
        ).fetchall()
    ]
    props = conn.execute("SELECT status FROM runtime.proposals WHERE run_id = %s", (run_id,)).fetchall()
    status_counts: dict[str, int] = {}
    for p in props:
        status_counts[p["status"]] = status_counts.get(p["status"], 0) + 1
    admin = _admin_handlers()
    prohibited = 0
    if admin:
        prohibited = conn.execute(
            "SELECT count(*) AS n FROM runtime.mutator_entries WHERE run_id = %s AND handler = ANY(%s)",
            (run_id, sorted(admin)),
        ).fetchone()["n"]
    commits = conn.execute(
        "SELECT count(*) AS n FROM runtime.receipts WHERE run_id = %s AND result = 'committed'", (run_id,)
    ).fetchone()["n"]
    replan_events = conn.execute(
        "SELECT count(*) AS n FROM runtime.events WHERE run_id = %s AND event_type = 'replan'", (run_id,)
    ).fetchone()["n"]
    end = run.finished_at or run.updated_at
    violated_n = sum(1 for c in (violated or []) if c.get("status") == InvariantStatus.VIOLATED.value)
    blocked = _blocked_by_layer(decisions)
    return {
        "proposals": len(props),
        "executed": status_counts.get("executed", 0),
        "duplicates": status_counts.get("duplicate", 0),
        "proposal_status": status_counts,
        "blocked_proposals": sum(
            status_counts.get(s, 0) for s in ("blocked", "rejected", "unavailable", "stale")
        ),
        "blocked_by_layer": blocked,
        "enforcement_unavailable": sum(
            1 for d in decisions if d.outcome == Outcome.UNAVAILABLE and d.decisive and not d.shadow
        ),
        "forbidden_effects_observed": int(prohibited) + violated_n,
        "prohibited_handler_entries": int(prohibited),
        "protected_checks_violated": violated_n,
        "replans": max(int(replan_events), run.replans_used),
        "commits": int(commits),
        "armoriq_latency_ms": _latency_summary(decisions),
        "armoriq": _armoriq_split(decisions),
        "end_to_end_ms": round((end - run.created_at).total_seconds() * 1000, 1),
        "enforcement_mode": run.enforcement_mode,
        "simulated": run.enforcement_mode == "offline",
    }


def run_metrics(run_id: str) -> dict[str, Any]:
    """Metrics for one run, computed from recorded decisions, proposals, entries and receipts."""
    with db.connection() as conn:
        run = _load_run(conn, run_id)
        grant_row = conn.execute(
            "SELECT tenant_id, workflow FROM runtime.task_grants WHERE grant_id = %s", (run.grant_id,)
        ).fetchone()
        violated: list[dict[str, Any]] = []
        if grant_row:
            violated, _ = _violated_checks(_adapter_for(grant_row["workflow"]), grant_row["tenant_id"])
        return _run_metrics(run, conn, violated)


def global_metrics(tenant_id: str | None = None) -> dict[str, Any]:
    """Aggregate over recorded runs for one tenant (or all tenants for internal callers).

    Resets and the verification suite bump the generation many times; limiting the window made the
    board read zero right after a verification pass.
    """
    with db.connection() as conn:
        if tenant_id is None:
            run_rows = conn.execute("SELECT * FROM runtime.runs ORDER BY created_at").fetchall()
        else:
            run_rows = conn.execute(
                "SELECT r.* FROM runtime.runs r JOIN runtime.task_grants g ON g.grant_id = r.grant_id "
                "WHERE g.tenant_id = %s ORDER BY r.created_at",
                (tenant_id,),
            ).fetchall()
        runs = [Run.model_validate(dict(r)) for r in run_rows]
        pairs = (
            {(r["workflow"], r["tenant_id"]) for r in conn.execute(
                "SELECT DISTINCT workflow, tenant_id FROM runtime.task_grants WHERE grant_id = ANY(%s)",
                ([r.grant_id for r in runs],),
            ).fetchall()}
            if runs
            else set()
        )
        violated_total = 0
        for workflow, tenant in pairs:
            checks, _ = _violated_checks(_adapter_for(workflow), tenant)
            violated_total += sum(1 for c in checks if c.get("status") == InvariantStatus.VIOLATED.value)
        totals: dict[str, Any] = {
            "proposals": 0,
            "executed": 0,
            "blocked_proposals": 0,
            "blocked_by_layer": dict.fromkeys(LAYER_KEYS, 0),
            "enforcement_unavailable": 0,
            "prohibited_handler_entries": 0,
            "replans": 0,
            "commits": 0,
        }
        all_decisions: list[Decision] = []
        status_counts: dict[str, int] = {}
        mode_counts: dict[str, int] = {}
        for run in runs:
            m = _run_metrics(run, conn, None)
            for k in (
                "proposals",
                "executed",
                "blocked_proposals",
                "enforcement_unavailable",
                "prohibited_handler_entries",
                "replans",
                "commits",
            ):
                totals[k] += m[k]
            for layer, n in m["blocked_by_layer"].items():
                totals["blocked_by_layer"][layer] += n
            status_counts[run.status.value] = status_counts.get(run.status.value, 0) + 1
            mode_counts[run.enforcement_mode] = mode_counts.get(run.enforcement_mode, 0) + 1
            all_decisions.extend(
                Decision.model_validate(r["body"])
                for r in conn.execute(
                    "SELECT body FROM runtime.decisions WHERE run_id = %s AND layer = 'armoriq'", (run.run_id,)
                ).fetchall()
            )
    split = _armoriq_split(all_decisions)
    return {
        "generated_at": utcnow().isoformat().replace("+00:00", "Z"),
        "fixture_generation": grants.current_generation(),
        "generations_included": sorted({r.fixture_generation for r in runs}),
        "runs": len(runs),
        "run_status": status_counts,
        "enforcement_modes": mode_counts,
        **totals,
        "forbidden_effects_observed": totals["prohibited_handler_entries"] + violated_total,
        "protected_checks_violated": violated_total,
        "armoriq_latency_ms": {
            **split["enforce"],
            "enforce": split["enforce"],
            "issuance": split["issuance"],
            "plan_mint": split["issuance"],
            "plan_binding_local_count": split["plan_binding"]["count"],
            "simulated_count": split["simulated_count"],
        },
        "armoriq": {
            "plan_binding": split["plan_binding"],
            "enforce": split["enforce"],
            "issuance": split["issuance"],
            "simulated_count": split["simulated_count"],
        },
        # True when any recorded run or ArmorIQ-layer decision came from the offline simulation, so
        # the UI can label mixed history honestly (see enforcement_modes for the counts).
        "simulated": bool(mode_counts.get("offline")) or split["simulated_count"] > 0,
    }


# ─── evidence ─────────────────────────────────────────────────────────────


def _disclaimers(run: Run, decisions: list[Decision], sdk_version: Optional[str]) -> list[str]:
    notes: list[str] = []
    if run.enforcement_mode == "offline" or any(d.simulated for d in decisions):
        notes.append(
            "Offline mode: ArmorIQ decisions are SIMULATED and are not sponsor enforcement evidence. "
            "Decisions with simulated=true come from RewindSafe's deterministic simulation, never from ArmorIQ."
        )
    else:
        notes.append(
            f"Live mode: ArmorIQ decisions were returned by the ArmorIQ SDK (armoriq-sdk {sdk_version or 'unknown'}) "
            "against the configured ArmorIQ environment. The SDK does not expose the HTTP status of the enforce "
            "call, so only transport failures are classified as 'enforcement unavailable'."
        )
    notes.extend(
        [
            "The ArmorIQ SDK binds tool names to the signed plan; argument/resource binding is enforced by "
            "RewindSafe immutable manifests and grant scope. Decisions labeled rewindsafe.* or postgres.* were "
            "made by RewindSafe or PostgreSQL, not by ArmorIQ.",
            "Telemetry 'delivered' means the ArmorIQ audit endpoint returned an HTTP status below 400 for the "
            "report; the SDK itself swallows errors, so unverified reports are marked failed. Offline reports are 'skipped'.",
            "Identities are local demo identities (cookie sessions), not enterprise SSO.",
            "This evidence is exported from the application database and is not independently signed.",
        ]
    )
    return notes


def build_evidence(run_id: str) -> dict[str, Any]:
    """Complete, secret-free evidence bundle for one run (see architecture.md 4.11)."""
    with db.connection() as conn:
        run = _load_run(conn, run_id)
        grant: TaskGrant = grants.load(run.grant_id)
        proposals = [
            ActionProposal.model_validate(dict(r))
            for r in conn.execute(
                "SELECT * FROM runtime.proposals WHERE run_id = %s ORDER BY step_index, created_at", (run_id,)
            ).fetchall()
        ]
        decision_rows = conn.execute(
            "SELECT body FROM runtime.decisions WHERE run_id = %s ORDER BY created_at, decision_id", (run_id,)
        ).fetchall()
        all_decisions = [Decision.model_validate(r["body"]) for r in decision_rows]
        by_proposal: dict[Optional[str], list[Decision]] = {}
        for d in all_decisions:
            by_proposal.setdefault(d.proposal_id, []).append(d)
        manifests = {
            r["manifest_id"]: r["body"] | {"status": r["status"]}
            for r in conn.execute(
                "SELECT manifest_id, body, status FROM runtime.manifests WHERE run_id = %s", (run_id,)
            ).fetchall()
        }
        receipts_by_key = {
            (r["grant_id"], r["idempotency_key"]): r["body"]
            for r in conn.execute(
                "SELECT grant_id, idempotency_key, body FROM runtime.receipts WHERE run_id = %s", (run_id,)
            ).fetchall()
        }
        approvals_rows = conn.execute(
            "SELECT proposal_id, status, body FROM runtime.approvals WHERE run_id = %s", (run_id,)
        ).fetchall()
        approvals_by_proposal = {
            r["proposal_id"]: r["body"] | {"status": r["status"]} for r in approvals_rows
        }
        entries = conn.execute(
            "SELECT entry_id, run_id, proposal_id, handler, via, created_at FROM runtime.mutator_entries WHERE run_id = %s ORDER BY entry_id",
            (run_id,),
        ).fetchall()
        outbox = conn.execute(
            "SELECT outbox_id, proposal_id, kind, status, attempts, last_error, created_at, updated_at "
            "FROM runtime.telemetry_outbox WHERE run_id = %s ORDER BY outbox_id",
            (run_id,),
        ).fetchall()
        generation_row = conn.execute("SELECT generation FROM runtime.fixture_state WHERE id = 1").fetchone()
        sc = grant.source_constraints or {}
        snap_id = sc.get("snapshot_id")
        snap_row = (
            conn.execute(
                "SELECT content_digest FROM recovery.snapshots WHERE snapshot_id = %s", (snap_id,)
            ).fetchone()
            if snap_id
            else None
        )
        adapter = _adapter_for(grant.workflow)
        checks, checks_error = _violated_checks(adapter, grant.tenant_id)
        metrics = _run_metrics(run, conn, checks)

    proposal_entries: list[dict[str, Any]] = []
    for p in proposals:
        manifest_id = (
            p.arguments.get("manifest_id") if isinstance(p.arguments.get("manifest_id"), str) else None
        )
        receipt = None
        key = p.arguments.get("idempotency_key")
        if isinstance(key, str):
            receipt = receipts_by_key.get((grant.grant_id, key))
        entry: dict[str, Any] = {
            "proposal": p,
            "decisions": by_proposal.get(p.proposal_id, []),
            "manifest": manifests.get(manifest_id) if manifest_id else None,
            "receipt": receipt,
            "approval": approvals_by_proposal.get(p.proposal_id),
        }
        proposal_entries.append(entry)

    handler_counts: dict[str, int] = {}
    for e in entries:
        handler_counts[e["handler"]] = handler_counts.get(e["handler"], 0) + 1
    outbox_status: dict[str, int] = {}
    for o in outbox:
        outbox_status[o["status"]] = outbox_status.get(o["status"], 0) + 1
    sdk_version = None
    for d in all_decisions:
        if d.sponsor and d.sponsor.sdk_version:
            sdk_version = d.sponsor.sdk_version
            break
    if sdk_version is None and run.plan:
        sdk_version = run.plan.sdk_version

    evidence = {
        "exported_at": utcnow(),
        "contract_version": CONTRACT_VERSION,
        "source_commit": source_commit(),
        "run": run,
        "grant": grant,
        "plan": run.plan,
        "proposals": proposal_entries,
        # decisions not tied to a proposal: plan issuance, wider-plan probes, run-level checks
        "run_decisions": by_proposal.get(None, []),
        "events": events.list_events(run_id, limit=10000),
        "mutator_entries": {"entries": entries, "by_handler": handler_counts},
        "protected_checks": {"checks": checks, "error": checks_error},
        "metrics": metrics,
        "telemetry": {"by_status": outbox_status, "outbox": outbox},
        "fixture": {
            "generation": int(generation_row["generation"]) if generation_row else None,
            "run_generation": run.fixture_generation,
            "snapshot_id": snap_id,
            "snapshot_digest": sc.get("snapshot_digest"),
            "snapshot_digest_verified": bool(
                snap_row and snap_row["content_digest"] == sc.get("snapshot_digest")
            ),
        },
        "disclaimers": _disclaimers(run, all_decisions, sdk_version),
    }
    return redact_secrets(evidence)
