"""W1: pure rules of approvals, grants, receipts and dispatch copy (no database)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from rewindsafe.contracts import (
    ApprovalRecord,
    ApprovalStatus,
    DecisionSource,
    GrantLimits,
    GrantStatus,
    Layer,
    Outcome,
    TaskGrant,
)
from rewindsafe.runtime.adapter import make_decision
from rewindsafe.runtime.approvals import payload_matches, separation_of_duties_violation
from rewindsafe.runtime.canonical import utcnow
from rewindsafe.runtime.dispatch import decision_copy
from rewindsafe.runtime.grants import assert_within_grant, compute_grant_digest, lifecycle_check
from rewindsafe.runtime.identities import IDENTITIES, get_identity
from rewindsafe.runtime.receipts import percentile

MAYA, DEV, SAM = IDENTITIES["maya"], IDENTITIES["dev"], IDENTITIES["sam"]


def approval(**kw) -> ApprovalRecord:
    now = utcnow()
    base = dict(
        approval_id="apr_1",
        run_id="run_1",
        grant_id="grt_1",
        proposal_id="prp_1",
        tool="apply_repair_manifest",
        manifest_id="mf_1",
        payload_digest="sha256:aaa",
        targets=["O-2046"],
        reason="high value",
        requested_by="maya",
        requested_at=now,
        expires_at=now + timedelta(minutes=10),
        state_constraints={"authority_epoch": 1, "row_versions": {"O-2046": 2}, "fixture_generation": 3},
    )
    base.update(kw)
    return ApprovalRecord(**base)


def grant(**kw) -> TaskGrant:
    now = utcnow()
    base = dict(
        grant_id="grt_1",
        workflow="rewindsafe.order_repair",
        scenario_id="clean",
        principal="maya",
        principal_email="nova.reyes@atlas.example",
        tenant_id="atlas",
        incident_id="INC-4471",
        purpose="repair",
        allowed_tools=["inspect_snapshot", "apply_repair_manifest"],
        resources={"order": ["O-2041", "O-2042"], "snapshot": ["SNAP-1"]},
        reviewable={"order": ["O-2046"]},
        fields=["total_cents"],
        prohibited_effects=["Restore access"],
        source_constraints={"snapshot_id": "SNAP-1", "snapshot_digest": "sha256:s"},
        status=GrantStatus.ACTIVE,
        created_at=now,
        expires_at=now + timedelta(minutes=30),
        fixture_generation=3,
        grant_digest="",
    )
    base.update(kw)
    g = TaskGrant(**base)
    return g.model_copy(update={"grant_digest": compute_grant_digest(g)})


# ── identities ───────────────────────────────────────────────────────────


def test_demo_identities_match_the_contract():
    assert set(IDENTITIES) == {"maya", "dev", "sam"}
    assert (MAYA.role, MAYA.tenant_id, MAYA.email) == ("operator", "atlas", "nova.reyes@atlas.example")
    assert (
        (DEV.role, DEV.tenant_id) == ("reviewer", "atlas") and DEV.initials == "OR" and DEV.color == "#34D399"
    )
    assert (SAM.role, SAM.tenant_id) == ("operator", "beacon")
    assert get_identity("dev") is DEV and get_identity("nobody") is None


# ── approvals: separation of duties ──────────────────────────────────────


def test_reviewer_of_same_tenant_who_is_not_the_requester_may_decide():
    assert separation_of_duties_violation(DEV, approval(), "atlas") is None


def test_operator_cannot_decide_even_if_not_the_requester():
    err = separation_of_duties_violation(SAM, approval(), "beacon")
    assert err and err.code == "reviewer_role_required"
    assert (
        separation_of_duties_violation(MAYA, approval(requested_by="someone-else"), "atlas").code
        == "reviewer_role_required"
    )


def test_reviewer_of_another_tenant_cannot_decide():
    other = DEV.model_copy(update={"tenant_id": "beacon"})
    assert separation_of_duties_violation(other, approval(), "atlas").code == "tenant_mismatch"


def test_requester_cannot_approve_their_own_action_even_as_reviewer():
    err = separation_of_duties_violation(DEV, approval(requested_by="dev"), "atlas")
    assert err and err.code == "separation_of_duties"


def test_payload_must_match_exactly():
    a = approval()
    assert payload_matches(a, "sha256:aaa")
    assert not payload_matches(a, "sha256:aab")
    assert payload_matches(a, "sha256:aaa", dict(a.state_constraints))
    changed = {**a.state_constraints, "row_versions": {"O-2046": 3}}
    assert not payload_matches(a, "sha256:aaa", changed)
    assert a.status == ApprovalStatus.PENDING


# ── grants ───────────────────────────────────────────────────────────────


def test_grant_digest_is_stable_and_covers_authority_fields_only():
    g = grant()
    assert g.grant_digest == compute_grant_digest(g) and g.grant_digest.startswith("sha256:")
    # lifecycle fields are NOT part of the digest
    assert (
        compute_grant_digest(g.model_copy(update={"commits_used": 1, "status": GrantStatus.EXHAUSTED}))
        == g.grant_digest
    )
    # authority-bearing fields are
    for change in (
        {"tenant_id": "beacon"},
        {"allowed_tools": ["inspect_snapshot", "apply_repair_manifest", "restore_access_grant"]},
        {"resources": {"order": ["O-2041", "O-2042", "B-3002"], "snapshot": ["SNAP-1"]}},
        {"fields": ["total_cents", "owner_account"]},
        {"limits": GrantLimits(max_commits=5)},
        {"expires_at": g.expires_at + timedelta(minutes=1)},
        {"fixture_generation": 4},
    ):
        assert compute_grant_digest(g.model_copy(update=change)) != g.grant_digest, change


def test_lifecycle_ok_for_an_active_grant():
    g = grant()
    assert lifecycle_check(g, 3, run_id="r") is None
    assert lifecycle_check(g, 3, run_id="r", tool_is_mutator=True) is None


@pytest.mark.parametrize(
    ("update", "invariant"),
    [
        ({"status": GrantStatus.DRAFT}, "grant_inactive"),
        ({"status": GrantStatus.REVOKED}, "grant_inactive"),
        ({"status": GrantStatus.EXPIRED}, "grant_inactive"),
        ({"expires_at": utcnow() - timedelta(seconds=1)}, "grant_expired"),
    ],
)
def test_lifecycle_blocks_unusable_grants(update, invariant):
    d = lifecycle_check(grant().model_copy(update=update), 3, run_id="run_1", proposal_id="prp_1")
    assert d.outcome == Outcome.BLOCK and d.decisive and d.layer == Layer.RUNTIME
    assert d.source == DecisionSource.LIFECYCLE and d.invariant == invariant
    assert d.run_id == "run_1" and d.proposal_id == "prp_1"


def test_lifecycle_blocks_wrong_generation_and_tampering():
    g = grant()
    assert lifecycle_check(g, 4).invariant == "fixture_generation"
    tampered = g.model_copy(update={"allowed_tools": [*g.allowed_tools, "restore_access_grant"]})
    assert lifecycle_check(tampered, 3).invariant == "grant_tampered"


def test_exhausted_grant_blocks_mutators_but_still_allows_reads():
    spent = grant().model_copy(update={"commits_used": 1, "status": GrantStatus.EXHAUSTED})
    assert lifecycle_check(spent, 3, tool_is_mutator=False) is None  # can still fetch the receipt
    d = lifecycle_check(spent, 3, tool_is_mutator=True)
    assert d.invariant == "grant_exhausted"
    # commits used up but status not yet flipped: mutators still blocked
    almost = grant().model_copy(update={"commits_used": 1})
    assert lifecycle_check(almost, 3, tool_is_mutator=True).invariant == "grant_exhausted"
    assert lifecycle_check(almost, 3) is None


def test_assert_within_grant_remint_guard():
    g = grant()
    assert assert_within_grant(g, ["inspect_snapshot"], {"order": ["O-2041"], "snapshot": ["SNAP-1"]}) is None
    assert assert_within_grant(g, [], {"order": ["O-2046"]}) is None  # reviewable is inside the grant
    d = assert_within_grant(
        g, ["inspect_snapshot", "restore_access_grant"], {"order": ["O-2041", "B-3002"]}, run_id="r"
    )
    assert (
        d.outcome == Outcome.BLOCK
        and d.invariant == "no_authority_expansion"
        and d.source == DecisionSource.GRANT_SCOPE
    )
    assert d.evidence["extra_tools"] == ["restore_access_grant"] and d.evidence["extra_resources"] == {
        "order": ["B-3002"]
    }
    assert assert_within_grant(g, [], {"customer": ["C-1003"]}).invariant == "no_authority_expansion"


# ── receipts / copy ──────────────────────────────────────────────────────


def test_percentile():
    assert percentile([], 0.5) is None
    assert percentile([10.0], 0.95) == 10.0
    assert percentile([10, 20, 30, 40], 0.5) == 25.0
    assert percentile([1, 2, 3, 4, 100], 0.95) == pytest.approx(80.8)


def test_decision_copy_is_plain_english_and_honest_about_simulation():
    live = make_decision(
        "r",
        DecisionSource.ARMORIQ_PLAN_BINDING,
        Outcome.BLOCK,
        "tool-not-in-plan: x",
        invariant="tool_not_in_signed_plan",
        decisive=True,
    )
    title, detail = decision_copy(live, "restore_access_grant")
    assert title == "ArmorIQ blocked restore_access_grant"
    assert "Not in the signed recovery plan" in detail and "handler was never entered" in detail

    sim = make_decision(
        "r",
        DecisionSource.ARMORIQ_SIMULATED,
        Outcome.BLOCK,
        "tool-not-in-plan: x",
        invariant="tool_not_in_signed_plan",
        decisive=True,
        simulated=True,
    )
    title, detail = decision_copy(sim, "restore_access_grant")
    assert title.startswith("Simulated ArmorIQ") and "not sponsor enforcement" in detail

    grant_block = make_decision(
        "r",
        DecisionSource.GRANT_SCOPE,
        Outcome.BLOCK,
        "Order B-3002 belongs to tenant beacon.",
        decisive=True,
    )
    assert (
        decision_copy(grant_block, "prepare_repair_manifest")[0]
        == "Grant scope blocked prepare_repair_manifest"
    )
    shadow = grant_block.model_copy(update={"shadow": True, "decisive": False})
    assert "would also have blocked" in decision_copy(shadow, "restore_access_grant")[0]
    down = make_decision("r", DecisionSource.ARMORIQ_ENFORCE, Outcome.UNAVAILABLE, "x", decisive=True)
    assert "not a policy denial" in decision_copy(down, "apply_repair_manifest")[1]
