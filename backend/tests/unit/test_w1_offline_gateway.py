"""W1: offline (simulated) ArmorIQ gateway semantics (no database)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from rewindsafe.config import Settings
from rewindsafe.contracts import DecisionSource, GrantStatus, Layer, Outcome, TaskGrant
from rewindsafe.runtime.armoriq_gateway import (
    OfflineSimulatedGateway,
    get_gateway,
    set_gateway_for_tests,
)
from rewindsafe.runtime.canonical import utcnow

TOOLS = [
    "inspect_snapshot",
    "compare_current",
    "prepare_repair_manifest",
    "apply_repair_manifest",
    "get_recovery_receipt",
]


def grant() -> TaskGrant:
    now = utcnow()
    return TaskGrant(
        grant_id="grt_x",
        workflow="rewindsafe.order_repair",
        scenario_id="poisoned",
        principal="maya",
        principal_email="nova.reyes@atlas.example",
        tenant_id="atlas",
        purpose="repair",
        allowed_tools=TOOLS,
        resources={"order": ["O-2041"]},
        status=GrantStatus.ACTIVE,
        created_at=now,
        expires_at=now + timedelta(minutes=30),
        fixture_generation=1,
        grant_digest="sha256:x",
    )


@pytest.fixture
def gw() -> OfflineSimulatedGateway:
    g = OfflineSimulatedGateway(Settings(_env_file=None))
    g.bind_plan("run_1", grant(), [{"name": t, "args": {}} for t in TOOLS], "nova.reyes@atlas.example")
    return g


def test_plan_binding_is_simulated_and_prefixed():
    g = OfflineSimulatedGateway(Settings(_env_file=None))
    calls = [{"name": t, "args": {}} for t in TOOLS]
    b = g.bind_plan("r", grant(), calls, "e@x")
    assert b.mode == "offline" and b.simulated is True
    assert b.plan_id.startswith("sim-") and b.token_id.startswith("sim-")
    assert b.plan_hash.startswith("sha256:") and b.steps == TOOLS
    # the plan hash is a digest of the plan: same plan -> same hash, different plan -> different hash
    assert g.bind_plan("r2", grant(), calls, "e@x").plan_hash == b.plan_hash
    assert g.bind_plan("r3", grant(), calls[:3], "e@x").plan_hash != b.plan_hash


def test_describe_is_honest():
    d = OfflineSimulatedGateway(Settings(_env_file=None)).describe()
    assert d["mode"] == "offline" and d["simulated"] is True and d["session_mode"] == "simulated"


def test_in_plan_read_is_allowed(gw):
    d = gw.check("run_1", "prp_1", "inspect_snapshot", {"tenant_id": "atlas"})
    assert d.outcome == Outcome.ALLOW and d.layer == Layer.ARMORIQ
    assert d.source == DecisionSource.ARMORIQ_SIMULATED and d.simulated is True
    assert d.sponsor.mode == "offline" and d.latency_ms is not None


def test_off_plan_tool_is_blocked_with_plan_binding_reason(gw):
    d = gw.check("run_1", "prp_1", "delete_everything", {})
    assert d.outcome == Outcome.BLOCK and d.simulated
    assert d.reason.startswith("tool-not-in-plan") and d.invariant == "tool_not_in_signed_plan"


def test_restore_access_grant_is_denied_even_if_someone_put_it_in_the_plan():
    g = OfflineSimulatedGateway(Settings(_env_file=None))
    g.bind_plan("r", grant(), [{"name": t, "args": {}} for t in [*TOOLS, "restore_access_grant"]], "e@x")
    d = g.check("r", "p", "restore_access_grant", {"tenant_id": "atlas", "grant_id": "AG-77"})
    assert d.outcome == Outcome.BLOCK and d.invariant == "org_policy_allowlist" and d.simulated
    assert "tool_not_in_allowlist (simulated" in d.reason


@pytest.fixture
def gw_threshold(monkeypatch) -> OfflineSimulatedGateway:
    monkeypatch.setenv("REWINDSAFE_SIM_HOLD_THRESHOLD", "5000")
    g = OfflineSimulatedGateway(Settings(_env_file=None))
    g.bind_plan("run_1", grant(), [{"name": t, "args": {}} for t in TOOLS], "nova.reyes@atlas.example")
    return g


def test_no_sponsor_hold_by_default_matching_the_live_workspace(gw):
    # live ArmorIQ has no HOLD threshold configured: amount 12400 is allowed (docs/architecture.md 1.1)
    d = gw.check("run_1", "prp_1", "apply_repair_manifest", {"manifest_id": "m", "amount": 12400})
    assert d.outcome == Outcome.ALLOW and d.simulated


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (1240.0, Outcome.ALLOW),
        (5000, Outcome.ALLOW),
        (5000.01, Outcome.HOLD),
        (12400, Outcome.HOLD),
        ("12400.00", Outcome.HOLD),
    ],
)
def test_apply_amount_threshold_only_when_configured(gw_threshold, amount, expected):
    d = gw_threshold.check("run_1", "prp_1", "apply_repair_manifest", {"manifest_id": "m", "amount": amount})
    assert d.outcome == expected
    if expected == Outcome.HOLD:
        assert d.sponsor.delegation_id.startswith("sim-deleg_") and d.invariant == "armoriq_hold"
        assert "NOT active in the live workspace" in d.reason


def test_apply_without_amount_is_default_denied(gw):
    d = gw.check("run_1", "prp_1", "apply_repair_manifest", {"manifest_id": "m"})
    assert d.outcome == Outcome.BLOCK


def test_same_held_action_reuses_its_delegation_id(gw_threshold):
    gw = gw_threshold
    args = {"manifest_id": "m", "amount": 12400}
    a = gw.check("run_1", "p1", "apply_repair_manifest", args)
    b = gw.check("run_1", "p1", "apply_repair_manifest", args)
    c = gw.check("run_1", "p1", "apply_repair_manifest", {**args, "manifest_id": "other"})
    assert a.sponsor.delegation_id == b.sponsor.delegation_id != c.sponsor.delegation_id


def test_force_unavailable_fails_closed_and_is_not_a_policy_denial(gw):
    gw.force_unavailable(True)
    d = gw.check("run_1", "p", "inspect_snapshot", {})
    assert d.outcome == Outcome.UNAVAILABLE and d.invariant == "enforcement_unavailable" and d.simulated
    gw.force_unavailable(False)
    assert gw.check("run_1", "p", "inspect_snapshot", {}).outcome == Outcome.ALLOW


def test_no_plan_bound_is_unavailable_and_close_run_forgets_the_plan(gw):
    assert gw.check("nope", "p", "inspect_snapshot", {}).outcome == Outcome.UNAVAILABLE
    gw.close_run("run_1")
    assert gw.check("run_1", "p", "inspect_snapshot", {}).outcome == Outcome.UNAVAILABLE


def test_probe_wider_plan_is_issued_then_blocked_at_check_like_live(gw):
    d = gw.probe_wider_plan("run_1", grant(), ["restore_access_grant"], "e@x")
    assert d.outcome == Outcome.BLOCK and d.simulated and d.source == DecisionSource.ARMORIQ_SIMULATED
    assert d.invariant == "org_policy_allowlist" and d.decisive
    assert "tool_not_in_allowlist (simulated" in d.reason
    assert d.evidence["extra_tools"] == ["restore_access_grant"]
    assert d.evidence["wider_plan_issued"] is True and d.evidence["wider_plan_blocked_at"] == "enforce"


def test_simulated_readiness_generation_and_shadow(gw):
    r = gw.readiness()
    assert r["state"] == "simulated"
    assert gw.record_generation("run_1", "m", 1, 2) is None
    sh = gw.shadow_backend_check("run_1", "p", "restore_access_grant", {"tenant_id": "beacon"})
    assert sh is not None and sh.shadow and not sh.decisive and sh.simulated
    assert gw.shadow_backend_check("run_1", "p", "inspect_snapshot", {}) is None
    b = gw.bind_plan("run_2", grant(), [{"name": "inspect_snapshot", "args": {}}], "e@x", llm="groq:x")
    assert b.latency_ms is not None and b.matched_policies
    gw.close_run("run_2", "succeeded")  # emits a simulated plan.completed event; never raises without a DB


def test_every_decision_is_labeled_simulated_never_as_a_real_armoriq_source(gw):
    for tool, args in [
        ("inspect_snapshot", {}),
        ("restore_access_grant", {}),
        ("apply_repair_manifest", {"amount": 1}),
        ("apply_repair_manifest", {"amount": 99999}),
        ("unknown", {}),
    ]:
        d = gw.check("run_1", "p", tool, args)
        assert d.simulated is True and d.source == DecisionSource.ARMORIQ_SIMULATED
        assert d.evidence["simulation"].startswith("Offline mode: this is a SIMULATED")


def test_evidence_does_not_echo_argument_values(gw):
    d = gw.check("run_1", "p", "inspect_snapshot", {"tenant_id": "atlas", "secret_note": "hunter2"})
    assert "hunter2" not in str(d.model_dump(mode="json"))
    assert d.evidence["argument_keys"] == ["secret_note", "tenant_id"]


def test_singleton_hooks():
    mine = OfflineSimulatedGateway(Settings(_env_file=None))
    try:
        set_gateway_for_tests(mine)
        assert get_gateway() is mine
    finally:
        set_gateway_for_tests(None)
