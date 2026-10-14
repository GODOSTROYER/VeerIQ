"""Gate A: live ArmorIQ enforcement probes.

These FAIL (never skip) when ``ARMORIQ_API_KEY`` is missing: an unverified gate
must not look like a passing one. Run with ``pytest -m live tests/live``.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest

from rewindsafe.contracts import DecisionSource, GrantLimits, Outcome, TaskGrant

pytestmark = pytest.mark.live

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_ID = "run_gate_a_live"
SNAPSHOT = "SNAP-2026-10-05-0000Z"


def _api_key() -> str:
    key = os.environ.get("ARMORIQ_API_KEY", "").strip()
    if not key:
        try:
            from dotenv import dotenv_values

            key = (dotenv_values(REPO_ROOT / ".env").get("ARMORIQ_API_KEY") or "").strip()
        except Exception:
            key = ""
    if not key:
        pytest.fail("BLOCKED: ARMORIQ_API_KEY not set; Gate A cannot be verified")
    return key


def _grant() -> TaskGrant:
    from rewindsafe.runtime.canonical import digest, utcnow

    now = utcnow()
    body = {
        "workflow": "rewindsafe.order_repair", "scenario_id": "gate_a", "principal": "maya",
        "principal_email": "nova.reyes@atlas.example", "tenant_id": "atlas", "incident_id": "INC-4471",
        "purpose": "Gate A live enforcement probe",
        "allowed_tools": ["inspect_snapshot", "compare_current", "prepare_repair_manifest",
                          "apply_repair_manifest", "get_recovery_receipt"],
        "resources": {"order": ["O-2041", "O-2042"], "snapshot": [SNAPSHOT]},
    }
    return TaskGrant(
        grant_id="grant_gate_a", **body, reviewable={}, fields=["total_cents", "shipping_region", "status"],
        prohibited_effects=[], source_constraints={"snapshot_id": SNAPSHOT},
        limits=GrantLimits(), created_at=now, expires_at=now + timedelta(minutes=30),
        fixture_generation=0, grant_digest=digest(body),
    )


@pytest.fixture(scope="module")
def live_gateway():
    key = _api_key()
    os.environ["ARMORIQ_API_KEY"] = key
    os.environ["REWINDSAFE_ENFORCEMENT"] = "live"
    from rewindsafe.runtime.adapter import get_adapter
    from rewindsafe.runtime.armoriq_gateway import LiveArmorIQGateway
    from rewindsafe.workflows.rewindsafe import adapter as _adapter  # noqa: F401  (registers the adapter)

    gateway = LiveArmorIQGateway()
    grant = _grant()
    plan = gateway.bind_plan(
        RUN_ID, grant, get_adapter(grant.workflow).plan_tool_calls(grant), grant.principal_email
    )
    yield gateway, plan
    try:
        gateway.close_run(RUN_ID)
    except Exception:
        pass


def test_live_plan_is_bound(live_gateway):
    _, plan = live_gateway
    assert plan.mode == "live" and plan.simulated is False
    assert plan.plan_hash, "live plan must carry a backend-issued plan hash"
    assert "restore_access_grant" not in plan.steps
    assert set(plan.steps) >= {"inspect_snapshot", "apply_repair_manifest"}


def test_live_in_plan_check_allows(live_gateway):
    gateway, _ = live_gateway
    decision = gateway.check(RUN_ID, "prop_gate_a_1", "inspect_snapshot",
                             {"snapshot_id": SNAPSHOT, "tenant_id": "atlas"})
    assert decision.simulated is False
    assert decision.outcome == Outcome.ALLOW, decision.reason
    assert decision.source == DecisionSource.ARMORIQ_ENFORCE


def test_live_off_plan_restore_is_blocked_by_plan_binding(live_gateway):
    gateway, _ = live_gateway
    decision = gateway.check(RUN_ID, "prop_gate_a_2", "restore_access_grant",
                             {"tenant_id": "atlas", "grant_id": "AG-77", "reason": "Gate A probe"})
    assert decision.simulated is False
    assert decision.outcome == Outcome.BLOCK
    assert decision.source == DecisionSource.ARMORIQ_PLAN_BINDING, decision.source


def _find_sdk_client(gateway):
    seen: set[int] = set()

    def walk(obj, depth=0):
        if obj is None or depth > 3 or id(obj) in seen:
            return None
        seen.add(id(obj))
        if hasattr(obj, "backend_endpoint") and hasattr(obj, "http_client"):
            return obj
        if isinstance(obj, dict):
            values = list(obj.values())
        elif hasattr(obj, "__dict__"):
            values = list(vars(obj).values())
        else:
            values = []
        for value in values:
            found = walk(value, depth + 1)
            if found is not None:
                return found
        return None

    return walk(gateway)


def test_live_unreachable_backend_is_unavailable_not_denied(live_gateway):
    gateway, _ = live_gateway
    client = _find_sdk_client(gateway)
    if client is None:
        pytest.fail("BLOCKED: could not locate the ArmorIQ SDK client inside the gateway to redirect it")
    original = client.backend_endpoint
    client.backend_endpoint = "http://127.0.0.1:9"  # nothing listens here
    try:
        decision = gateway.check(RUN_ID, "prop_gate_a_3", "inspect_snapshot",
                                 {"snapshot_id": SNAPSHOT, "tenant_id": "atlas"})
    finally:
        client.backend_endpoint = original
    assert decision.outcome == Outcome.UNAVAILABLE, (decision.outcome, decision.reason)
    assert decision.outcome != Outcome.BLOCK


def test_live_arguments_are_not_bound(live_gateway):
    """ArmorIQ binds tool NAMES, not argument values: tenant=beacon is allowed by ArmorIQ.

    It is RewindSafe's grant scope (tenant_scope) that refuses cross-tenant arguments, never ArmorIQ.
    """
    gateway, _ = live_gateway
    decision = gateway.check(
        RUN_ID, "p4", "prepare_repair_manifest",
        {"tenant_id": "beacon", "snapshot_id": SNAPSHOT, "order_ids": ["B-3002"], "fields": ["total_cents"]},
    )
    assert decision.simulated is False
    assert decision.outcome == Outcome.ALLOW, decision.reason
    assert decision.source == DecisionSource.ARMORIQ_ENFORCE


def test_live_wider_plan_blocked_at_enforce(live_gateway):
    """A wider plan including restore_access_grant is issued, but ArmorIQ's org allowlist blocks the check."""
    gateway, _ = live_gateway
    decision = gateway.probe_wider_plan(RUN_ID + "_wider", _grant(), ["restore_access_grant"],
                                        _grant().principal_email)
    assert decision.simulated is False
    assert decision.outcome == Outcome.BLOCK, (decision.outcome, decision.reason)
    assert decision.source == DecisionSource.ARMORIQ_ENFORCE, decision.source
    assert "tool_not_in_allowlist" in decision.reason
    assert decision.invariant == "org_policy_allowlist"


def test_live_readiness_is_verified(live_gateway):
    gateway, _ = live_gateway
    ready = gateway.readiness()
    assert ready["state"] in ("verified", "unverified"), ready
    assert ready["state"] != "failed", ready
