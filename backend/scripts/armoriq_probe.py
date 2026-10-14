"""Gate A: live ArmorIQ probe (no application database needed).

Answers, against the REAL ArmorIQ backend, the questions the architecture depends on:

  1. does a signed plan over the five recovery tools get issued?           (bind)
  2. is an in-plan read allowed?                                            (expect allow)
  3. is ``restore_access_grant`` (not in the plan) blocked?                 (expect block, plan binding)
  4. does ArmorIQ bind ARGUMENTS? same tool, altered tenant argument        (record whatever is returned)
  5. does an amount above 5000 produce a hold?                              (record hold or not)
  6. will ArmorIQ sign a WIDER plan that includes restore_access_grant?     (live-observed: issued, then
     blocked at ``check`` by the org allowlist, reason ``tool_not_in_allowlist``)
  7. is an unreachable backend classified UNAVAILABLE, not a policy block?  (expect unavailable)
  8. is the plan closed with ``complete_plan`` at the end of the run?       (record HTTP status)

Writes sanitized evidence to ``evidence/gate-a-<UTC timestamp>.json`` and prints a table.
Exit codes: 0 = a live allow AND a live off-plan block were observed; 1 = probe ran but the gate
was not met; 2 = blocked (missing ARMORIQ_API_KEY / user email).

Side effect to be aware of: step 5 may create a pending *delegation request* in the ArmorIQ org (that is
what a HOLD is). It is never approved or executed by this script.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from rewindsafe.config import get_settings  # noqa: E402
from rewindsafe.contracts import (  # noqa: E402
    Decision,
    DecisionSource,
    GrantLimits,
    GrantStatus,
    Outcome,
    TaskGrant,
)
from rewindsafe.runtime import armoriq_gateway as gateway_module  # noqa: E402
from rewindsafe.runtime.armoriq_gateway import LiveArmorIQGateway, sdk_version  # noqa: E402
from rewindsafe.runtime.canonical import digest, redact_secrets, to_jsonable, utcnow  # noqa: E402

RECOVERY_TOOLS = [
    "inspect_snapshot",
    "compare_current",
    "prepare_repair_manifest",
    "apply_repair_manifest",
    "get_recovery_receipt",
]
UNREACHABLE_BACKEND = "http://127.0.0.1:9"  # discard port: connection refused
SNAPSHOT_ID = "SNAP-2026-10-05-0000Z"


def probe_grant(email: str) -> TaskGrant:
    now = utcnow()
    return TaskGrant(
        grant_id="grt_gate_a_probe",
        workflow="rewindsafe.order_repair",
        scenario_id="gate-a",
        principal="probe",
        principal_email=email,
        tenant_id="atlas",
        incident_id="INC-4471",
        purpose="Gate A probe: repair damaged orders from an approved snapshot",
        allowed_tools=RECOVERY_TOOLS,
        resources={"order": ["O-2041", "O-2042"]},
        status=GrantStatus.ACTIVE,
        limits=GrantLimits(),
        created_at=now,
        expires_at=now + timedelta(minutes=30),
        fixture_generation=0,
        grant_digest="sha256:probe",
    )


def plan_calls() -> list[dict]:
    return [
        {"name": "inspect_snapshot", "args": {"snapshot_id": SNAPSHOT_ID, "tenant_id": "atlas"}},
        {"name": "compare_current", "args": {"tenant_id": "atlas", "order_ids": ["O-2041", "O-2042"]}},
        {"name": "prepare_repair_manifest", "args": {"tenant_id": "atlas", "snapshot_id": SNAPSHOT_ID}},
        {"name": "apply_repair_manifest", "args": {"manifest_id": "mf_probe"}},
        {"name": "get_recovery_receipt", "args": {"manifest_id": "mf_probe"}},
    ]


def row(step: str, expected: str, d: Decision | None, ok: bool | None, note: str = "") -> dict:
    return {
        "step": step,
        "expected": expected,
        "outcome": d.outcome.value if d else None,
        "source": d.source.value if d else None,
        "matched_policy": d.sponsor.matched_policy if d and d.sponsor else None,
        "raw_action": d.sponsor.raw_action if d and d.sponsor else None,
        "delegation_id_present": bool(d and d.sponsor and d.sponsor.delegation_id),
        "reason": d.reason if d else None,
        "latency_ms": round(d.latency_ms, 1) if d and d.latency_ms is not None else None,
        "as_expected": ok,
        "note": note,
        "decision": to_jsonable(d) if d else None,
    }


def run_probe(email: str) -> tuple[list[dict], dict]:
    settings = get_settings()
    gw = LiveArmorIQGateway(settings)
    run_id = "gate-a-" + utcnow().strftime("%Y%m%dT%H%M%SZ")
    grant = probe_grant(email)
    rows: list[dict] = []
    facts: dict = {}

    binding, bind_decision = gw.bind_plan_with_decision(
        run_id, grant, plan_calls(), email, llm="rewindsafe-gate-a-probe"
    )
    facts["plan"] = to_jsonable(binding)
    rows.append(
        row(
            "1 bind signed plan (5 recovery tools)",
            "allow (plan issued)",
            bind_decision,
            bind_decision.outcome == Outcome.ALLOW,
            binding.error or "",
        )
    )
    if binding.error:
        facts["aborted"] = "plan could not be issued; later checks would all fail closed and prove nothing"
        gw.close_run(run_id)
        return rows, facts

    read_args = {"snapshot_id": SNAPSHOT_ID, "tenant_id": "atlas", "order_ids": ["O-2041"]}
    d = gw.check(run_id, "prp_probe_read", "inspect_snapshot", read_args)
    rows.append(row("2 in-plan read: inspect_snapshot", "allow", d, d.outcome == Outcome.ALLOW))
    facts["live_allow_observed"] = d.outcome == Outcome.ALLOW and d.source == DecisionSource.ARMORIQ_ENFORCE

    priv_args = {"tenant_id": "atlas", "grant_id": "AG-77", "reason": "probe"}
    d = gw.check(run_id, "prp_probe_priv", "restore_access_grant", priv_args)
    blocked_by_plan = d.outcome == Outcome.BLOCK and d.source == DecisionSource.ARMORIQ_PLAN_BINDING
    rows.append(
        row("3 off-plan privileged tool: restore_access_grant", "block via plan binding", d, blocked_by_plan)
    )
    facts["live_off_plan_block_observed"] = blocked_by_plan

    base = {"manifest_id": "mf_probe", "manifest_digest": "sha256:probe", "idempotency_key": "probe-1"}
    atlas_args = {**base, "tenant_id": "atlas", "order_ids": ["O-2041"], "amount": 1240.0}
    control = gw.check(run_id, "prp_probe_ctl", "apply_repair_manifest", atlas_args)
    rows.append(row("4a apply (control): tenant atlas, $1,240", "record result", control, None))
    beacon_args = {**base, "tenant_id": "beacon", "order_ids": ["B-3002"], "amount": 1240.0}
    altered = gw.check(run_id, "prp_probe_alt", "apply_repair_manifest", beacon_args)
    same = (control.outcome, control.sponsor.matched_policy if control.sponsor else None) == (
        altered.outcome,
        altered.sponsor.matched_policy if altered.sponsor else None,
    )
    note = (
        "identical decision for atlas and beacon: NO argument binding observed "
        "(RewindSafe manifests/grant scope must enforce it)"
        if same
        else "decision differs when the tenant argument changes: ArmorIQ policy IS argument-aware for this field"
    )
    rows.append(
        row("4b apply with ALTERED tenant argument (beacon / B-3002)", "record result", altered, None, note)
    )
    facts["argument_binding_observed"] = not same
    facts["argument_non_binding_beacon_allowed"] = (
        altered.outcome == Outcome.ALLOW and control.outcome == Outcome.ALLOW
    )

    big_args = {**base, "tenant_id": "atlas", "order_ids": ["O-2046"], "amount": 12400.0}
    hold = gw.check(run_id, "prp_probe_hold", "apply_repair_manifest", big_args)
    rows.append(
        row(
            "5 apply with amount 12400",
            "record (hold only if a dashboard amount threshold is configured; none is today)",
            hold,
            None,
            "hold observed"
            if hold.outcome == Outcome.HOLD
            else f"no hold (outcome {hold.outcome.value}): no amount threshold is configured in the workspace; "
            "the review scenario's HOLD comes from RewindSafe's own reviewable set",
        )
    )
    facts["hold_observed"] = hold.outcome == Outcome.HOLD

    wider = gw.probe_wider_plan(run_id, grant, ["restore_access_grant"], email)
    rows.append(
        row(
            "6 wider plan incl. restore_access_grant",
            "record issuance result",
            wider,
            None,
            "wider plan ISSUED, then blocked at enforcement by the org allowlist"
            if wider.evidence.get("wider_plan_blocked_at") == "enforce"
            else "issuance REFUSED by org policy"
            if wider.evidence.get("wider_plan_blocked_at") == "issuance"
            else f"result: {wider.outcome.value}",
        )
    )
    facts["wider_plan_refused"] = wider.outcome == Outcome.BLOCK
    facts["wider_plan_blocked_at"] = wider.evidence.get("wider_plan_blocked_at")
    facts["wider_plan_issued"] = bool(
        wider.evidence.get("wider_plan_issued") or wider.evidence.get("wider_plan_blocked_at") == "enforce"
    )
    facts["wider_plan_block_invariant"] = wider.invariant
    facts["wider_plan_block_reason"] = wider.reason

    original = gw.client.backend_endpoint
    try:
        gw.client.backend_endpoint = UNREACHABLE_BACKEND
        d = gw.check(run_id, "prp_probe_down", "apply_repair_manifest", atlas_args)
    finally:
        gw.client.backend_endpoint = original
    rows.append(
        row(
            "7 unreachable enforcement endpoint",
            "unavailable (fail closed, not a policy denial)",
            d,
            d.outcome == Outcome.UNAVAILABLE,
        )
    )
    facts["unavailable_classified"] = d.outcome == Outcome.UNAVAILABLE

    # 8: close the run: complete_plan (best effort) + observability flush. Capture the lifecycle record.
    captured: list[dict] = []
    original_emit = gateway_module._emit_plan_lifecycle
    gateway_module._emit_plan_lifecycle = lambda rid, data, *, simulated: captured.append(dict(data))
    try:
        gw.close_run(run_id, "succeeded")
    finally:
        gateway_module._emit_plan_lifecycle = original_emit
    lifecycle = captured[0] if captured else {}
    facts["complete_plan_called"] = bool(lifecycle.get("plan_id")) and (
        bool(lifecycle.get("completed")) or lifecycle.get("http_status") is not None
    )
    facts["complete_plan"] = {
        "plan_id_present": bool(lifecycle.get("plan_id")),
        "completed": lifecycle.get("completed"),
        "http_status": lifecycle.get("http_status"),
        "note": lifecycle.get("reason"),
        "observability_http_status": lifecycle.get("observability_http_status"),
    }
    rows.append(
        {
            "step": "8 complete_plan at end of run",
            "expected": "plan marked completed (HTTP < 400)",
            "outcome": "completed" if lifecycle.get("completed") else "not completed",
            "source": "armoriq.backend.plan_status",
            "matched_policy": None,
            "raw_action": None,
            "delegation_id_present": False,
            "reason": lifecycle.get("reason"),
            "latency_ms": None,
            "as_expected": bool(lifecycle.get("completed")),
            "note": f"HTTP {lifecycle.get('http_status')}",
            "decision": None,
        }
    )
    return rows, facts


def print_table(rows: list[dict]) -> None:
    headers = ("step", "expected", "observed", "source", "ms", "ok")
    data = [
        (
            r["step"],
            r["expected"],
            r["outcome"] or "-",
            (r["source"] or "-").replace("armoriq.", ""),
            "-" if r["latency_ms"] is None else f"{r['latency_ms']:.0f}",
            {True: "yes", False: "NO", None: "n/a"}[r["as_expected"]],
        )
        for r in rows
    ]
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *data, strict=True)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))
    print(line)
    print("-" * len(line))
    for rec in data:
        print("  ".join(str(c).ljust(w) for c, w in zip(rec, widths, strict=True)))
    for r in rows:
        if r["note"]:
            print(f"  note [{r['step'].split()[0]}]: {r['note']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gate A live ArmorIQ probe")
    ap.add_argument("--user-email", default="", help="ArmorIQ user email (defaults to ARMORIQ_USER_EMAIL)")
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "evidence"))
    args = ap.parse_args(argv)

    settings = get_settings()
    if not settings.armoriq_configured:
        print("GATE A: BLOCKED - ARMORIQ_API_KEY not set")
        return 2
    email = (args.user_email or settings.armoriq_user_email).strip()
    if not email:
        print("GATE A: BLOCKED - ARMORIQ_USER_EMAIL not set (or pass --user-email)")
        return 2

    started = datetime.now(UTC)
    error: str | None = None
    rows: list[dict] = []
    facts: dict = {}
    try:
        rows, facts = run_probe(email)
    except Exception as exc:  # noqa: BLE001 - the evidence file must still be written
        error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()

    passed = (
        bool(facts.get("live_allow_observed") and facts.get("live_off_plan_block_observed")) and error is None
    )
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    evidence = {
        "gate": "A",
        "started_at": started,
        "finished_at": datetime.now(UTC),
        "passed": passed,
        "sdk_version": sdk_version(),
        "armoriq_env": settings.armoriq_env,
        "session_mode": settings.armoriq_session_mode,
        "mcp_name": settings.armoriq_mcp_name,
        "user_email_domain": email.split("@")[-1],
        "findings": facts,
        "steps": rows,
        "error": error,
        "plan_tools_digest": digest(RECOVERY_TOOLS),
        "notes": [
            "Decisions are exactly what the ArmorIQ SDK/backend returned; none are simulated.",
            "Step 5 may leave a pending ArmorIQ delegation request (only if a dashboard threshold exists); it is never approved or executed here.",
            "Step 6: a wider plan is issued and then blocked at enforcement by the org allowlist (tool_not_in_allowlist).",
            "Step 8 calls client.complete_plan on the probe plan after the checks above.",
        ],
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"gate-a-{stamp}.json"
    path.write_text(json.dumps(redact_secrets(evidence), indent=2, ensure_ascii=False), encoding="utf-8")

    if rows:
        print_table(rows)
    print(f"\nevidence: {path}")
    print(
        "GATE A: PASSED (live allow + live off-plan block observed)"
        if passed
        else "GATE A: NOT MET (need a live allow AND a live off-plan block)"
        + (f" - error: {error}" if error else "")
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
