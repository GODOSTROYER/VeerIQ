"""W1: live ArmorIQ gateway classification, sanitization and plan binding with a FAKE SDK (no network, no DB)."""

from __future__ import annotations

import json
import threading
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from rewindsafe.config import Settings
from rewindsafe.contracts import DecisionSource, GrantStatus, Layer, Outcome, TaskGrant
from rewindsafe.runtime.armoriq_gateway import LiveArmorIQGateway, classify_enforce_result
from rewindsafe.runtime.canonical import utcnow

TOOLS = [
    "inspect_snapshot",
    "compare_current",
    "prepare_repair_manifest",
    "apply_repair_manifest",
    "get_recovery_receipt",
]
API_KEY = "ak_live_SUPERSECRETKEY123456"
JWT = "eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJl"


def er(
    action: Any,
    allowed: Any,
    reason: str | None = "",
    delegation_id: str | None = None,
    matched: str | None = None,
    obligations: list | None = None,
):
    return SimpleNamespace(
        action=action,
        allowed=allowed,
        reason=reason,
        delegation_id=delegation_id,
        matched_policy=matched,
        obligations=obligations or [],
    )


class FakeSession:
    def __init__(self, result: Any = None, exc: Exception | None = None):
        self.result, self.exc = result, exc
        self.calls: list[tuple] = []
        self.closed = False
        self.approval_result: Any = "approved"

    def check(self, tool, args, user_email=None):
        self.calls.append((tool, args, user_email))
        if self.exc:
            raise self.exc
        return self.result

    async def await_approval(self, delegation_id, *, timeout, interval, user_email=None):
        await asyncio.sleep(0)
        if isinstance(self.approval_result, Exception):
            raise self.approval_result
        return self.approval_result

    def close(self):
        self.closed = True


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


def gateway_with(session: FakeSession) -> LiveArmorIQGateway:
    gw = LiveArmorIQGateway(Settings(_env_file=None), client_factory=lambda: SimpleNamespace())
    from rewindsafe.contracts import PlanBinding

    gw.attach_session_for_tests(
        "run_1",
        session,
        PlanBinding(
            mode="live",
            simulated=False,
            plan_id="plan_abc",
            plan_hash="deadbeefcafe1234",
            token_id="intent_1",
            steps=TOOLS,
        ),
    )
    return gw


# ── pure classification: every reason prefix -> correct source/outcome ─────


@pytest.mark.parametrize(
    ("result", "source", "outcome"),
    [
        (
            er("block", False, "tool-not-in-plan: 'x' was not declared in the captured plan"),
            DecisionSource.ARMORIQ_PLAN_BINDING,
            Outcome.BLOCK,
        ),
        (
            er("block", False, "enforce-unavailable: ConnectError"),
            DecisionSource.ARMORIQ_ENFORCE,
            Outcome.UNAVAILABLE,
        ),
        (er("allow", True, "Allowed by policy"), DecisionSource.ARMORIQ_ENFORCE, Outcome.ALLOW),
        (
            er("block", False, "Tool denied by policy 'p'", matched="p"),
            DecisionSource.ARMORIQ_ENFORCE,
            Outcome.BLOCK,
        ),
        (
            er("hold", False, "needs approval", delegation_id="d-1"),
            DecisionSource.ARMORIQ_ENFORCE,
            Outcome.HOLD,
        ),
    ],
)
def test_classification_by_reason_and_action(result, source, outcome):
    c = classify_enforce_result(result)
    assert (c.source, c.outcome) == (source, outcome)


@pytest.mark.parametrize(
    "result",
    [
        er("ALLOW", True),  # case matters: exact strings only
        er("allow_log", True),
        er("deny", False),
        er(None, True),
        er("", False),
        er("allow", False),  # inconsistent
        er("allow", None),
        er("hold", True, delegation_id="d"),  # inconsistent
        er("permit", True),
    ],
)
def test_anything_but_exact_allow_block_hold_fails_closed(result):
    c = classify_enforce_result(result)
    assert c.outcome == Outcome.BLOCK
    assert c.outcome != Outcome.ALLOW


def test_hold_without_a_delegation_id_cannot_be_approved_so_it_is_refused_as_unavailable():
    c = classify_enforce_result(er("hold", False, "needs approval", delegation_id=None))
    assert c.outcome == Outcome.UNAVAILABLE and c.invariant == "hold_without_delegation"


def test_tool_not_in_plan_wins_even_if_action_says_allow():
    assert classify_enforce_result(er("allow", True, "tool-not-in-plan: x")).outcome == Outcome.BLOCK


# ── gateway.check ────────────────────────────────────────────────────────


def test_check_maps_a_plan_binding_block_and_times_the_call():
    s = FakeSession(
        er("block", False, "tool-not-in-plan: 'restore_access_grant' was not declared in the captured plan")
    )
    d = gateway_with(s).check("run_1", "prp_1", "restore_access_grant", {"tenant_id": "atlas"})
    assert (
        d.layer == Layer.ARMORIQ
        and d.source == DecisionSource.ARMORIQ_PLAN_BINDING
        and d.outcome == Outcome.BLOCK
    )
    assert d.simulated is False and d.latency_ms is not None and d.latency_ms >= 0
    assert (
        d.sponsor.mode == "live"
        and d.sponsor.plan_hash == "deadbeefcafe1234"
        and d.sponsor.token_id == "intent_1"
    )
    assert (
        s.calls == [("restore_access_grant", {"tenant_id": "atlas"}, None)]
        or s.calls[0][0] == "restore_access_grant"
    )


def test_check_hold_carries_delegation_and_policy():
    s = FakeSession(
        er(
            "hold",
            False,
            "Amount 12400 requires approval",
            delegation_id="deleg-9",
            matched="rewindsafe-recovery",
            obligations=[{"type": "approval"}],
        )
    )
    d = gateway_with(s).check("run_1", "p", "apply_repair_manifest", {"amount": 12400})
    assert d.outcome == Outcome.HOLD and d.sponsor.delegation_id == "deleg-9"
    assert d.sponsor.matched_policy == "rewindsafe-recovery" and d.sponsor.raw_action == "hold"
    assert d.sponsor.obligations == [{"type": "approval"}]


def test_check_exception_is_unavailable_never_allow():
    d = gateway_with(FakeSession(exc=RuntimeError(f"boom with key {API_KEY}"))).check(
        "run_1", "p", "inspect_snapshot", {}
    )
    assert d.outcome == Outcome.UNAVAILABLE and API_KEY not in json.dumps(d.model_dump(mode="json"))


def test_audit_response_id_is_normalized_only_from_valid_success_ack(monkeypatch):
    import httpx

    from rewindsafe.runtime import armoriq_gateway

    audit_id = "224dbcbd-6d86-48a2-8bdd-53fc82ee9a4d"
    emitted = []
    monkeypatch.setattr(armoriq_gateway, "_outbox_insert", lambda *_args: 1)
    monkeypatch.setattr(armoriq_gateway, "_outbox_finish", lambda *_args: None)
    monkeypatch.setattr(armoriq_gateway.events, "emit", lambda *args, **kwargs: emitted.append(kwargs))

    class Client:
        def __init__(self):
            self.http_client = SimpleNamespace(event_hooks={"response": []})

    client = Client()
    gw = LiveArmorIQGateway(Settings(_env_file=None), client_factory=lambda: client)
    gw._install_audit_hook(client)

    class Session:
        status = 200
        body = {"audit_id": audit_id}
        raises = False

        def report(self, *_args, **_kwargs):
            if self.raises:
                raise RuntimeError("transport failed")
            response = httpx.Response(
                self.status,
                json=self.body,
                request=httpx.Request("POST", "https://api.example/iap/audit"),
            )
            for hook in client.http_client.event_hooks["response"]:
                hook(response)

    session = Session()
    gw.attach_session_for_tests("audit-run", session)
    gw.report("audit-run", "proposal-1", "inspect_snapshot", {}, {}, "success")
    data = emitted[-1]["data"]
    assert data["audit_report_id"] == audit_id
    assert data["audit_report_id_source"] == "armoriq.audit_response.audit_id"

    session.status = 500
    session.body = {"audit_id": audit_id}
    gw.report("audit-run", "proposal-2", "inspect_snapshot", {}, {}, "success")
    assert "audit_report_id" not in emitted[-1]["data"]

    session.status = 200
    session.body = {}
    gw.report("audit-run", "proposal-3a", "inspect_snapshot", {}, {}, "success")
    assert "audit_report_id" not in emitted[-1]["data"]

    session.body = {"audit_id": "not-a-uuid"}
    gw.report("audit-run", "proposal-3b", "inspect_snapshot", {}, {}, "success")
    assert "audit_report_id" not in emitted[-1]["data"]

    session.raises = True
    gw.report("audit-run", "proposal-4", "inspect_snapshot", {}, {}, "success")
    assert emitted[-1]["data"]["status"] == "failed"
    assert "audit_report_id" not in emitted[-1]["data"]


def test_check_without_a_bound_plan_is_unavailable():
    gw = LiveArmorIQGateway(Settings(_env_file=None), client_factory=lambda: SimpleNamespace())
    assert gw.check("none", "p", "inspect_snapshot", {}).outcome == Outcome.UNAVAILABLE


def test_force_unavailable_never_reaches_the_session():
    s = FakeSession(er("allow", True))
    gw = gateway_with(s)
    gw.force_unavailable(True)
    assert gw.check("run_1", "p", "inspect_snapshot", {}).outcome == Outcome.UNAVAILABLE and s.calls == []
    gw.force_unavailable(False)
    assert gw.check("run_1", "p", "inspect_snapshot", {}).outcome == Outcome.ALLOW


def test_sanitization_never_leaks_keys_tokens_or_proofs():
    dirty = er(
        "block",
        False,
        f"denied; api_key={API_KEY} jwt {JWT}",
        matched="p",
        obligations=[{"jwt_token": JWT, "step_proofs": [1, 2], "api_key": API_KEY, "type": "x"}],
    )
    d = gateway_with(FakeSession(dirty)).check(
        "run_1", "p", "apply_repair_manifest", {"amount": 1, "api_key": API_KEY}
    )
    blob = json.dumps(d.model_dump(mode="json"))
    for secret in (API_KEY, JWT, "SUPERSECRETKEY"):
        assert secret not in blob
    assert d.sponsor.obligations[0]["type"] == "x"
    assert d.evidence["argument_keys"] == ["amount", "api_key"] and API_KEY not in blob


# ── bind_plan with a fake client ─────────────────────────────────────────


class FakeClient:
    def __init__(self, token=None, exc: Exception | None = None):
        self.token, self.exc = token, exc
        self.user_email_override = None
        self.sessions: list[Any] = []

    def for_user(self, email):
        client = self

        class Scope:
            def start_session(self, opts):
                sess = FakeBindSession(client, opts)
                client.sessions.append(sess)
                return sess

        return Scope()


class FakeBindSession(FakeSession):
    def __init__(self, client, opts):
        super().__init__()
        self.client, self.opts = client, opts

    def start_plan(self, tool_calls, goal=None):
        if self.client.exc:
            raise self.client.exc
        return self.client.token


def token():
    return SimpleNamespace(
        plan_id="plan_1",
        plan_hash="abcd" * 16,
        token_id="intent_77",
        issued_at=1_790_000_000.0,
        expires_at=1_790_001_800.0,
        total_steps=5,
        policy_snapshot=[{"policyName": "p"}],
        policy_validation={"allowed_tools": TOOLS, "denied_tools": [], "default_enforcement_action": "allow"},
        jwt_token=JWT,
        raw_token={"secret": "x"},
        step_proofs=[1, 2, 3],
    )


def make_gw(client: FakeClient) -> LiveArmorIQGateway:
    return LiveArmorIQGateway(
        Settings(
            _env_file=None,
        ),
        client_factory=lambda: client,
    )


def test_bind_plan_success_maps_the_token_without_leaking_it():
    client = FakeClient(token=token())
    gw = make_gw(client)
    binding, decision = gw.bind_plan_with_decision(
        "run_9", grant(), [{"name": t, "args": {}} for t in TOOLS], "Nova.Reyes@Atlas.example"
    )
    assert binding.mode == "live" and binding.simulated is False and binding.error is None
    assert binding.plan_id == "plan_1" and binding.token_id == "intent_77" and binding.steps == TOOLS
    assert binding.issued_at is not None and binding.expires_at > binding.issued_at
    assert decision.outcome == Outcome.ALLOW and decision.source == DecisionSource.ARMORIQ_TOKEN_ISSUANCE
    blob = json.dumps(decision.model_dump(mode="json")) + json.dumps(binding.model_dump(mode="json"))
    assert JWT not in blob and "step_proofs" not in blob and "raw_token" not in blob
    opts = client.sessions[0].opts
    assert (
        opts.mode == "sdk"
        and opts.default_mcp_name == "rewindsafe-recovery"
        and opts.validity_seconds == 1800
    )
    assert client.user_email_override == "nova.reyes@atlas.example"
    assert gw.get_bind_decision("run_9") is decision
    gw.close_run("run_9")


def test_policy_blocked_issuance_becomes_binding_error_and_issuance_decision():
    from armoriq_sdk.exceptions import PolicyBlockedException

    exc = PolicyBlockedException(
        "Policy blocked intent token issuance: restore_access_grant:denied",
        enforcement_action="block",
        reason="restore_access_grant: denied by policy rewindsafe-recovery",
        metadata={
            "denied_tools": ["restore_access_grant"],
            "denied_reasons": ["restore_access_grant:denied"],
            "default_enforcement_action": "block",
        },
    )
    gw = make_gw(FakeClient(exc=exc))
    binding, decision = gw.bind_plan_with_decision(
        "run_9", grant(), [{"name": "restore_access_grant", "args": {}}], "a@b.c"
    )
    assert binding.error and "refused to sign" in binding.error and binding.plan_hash is None
    assert (
        decision.outcome == Outcome.BLOCK
        and decision.source == DecisionSource.ARMORIQ_TOKEN_ISSUANCE
        and decision.decisive
    )
    assert decision.sponsor.sanitized_response["denied_tools"] == ["restore_access_grant"]
    # a run with no signed plan can never pass a check
    after = gw.check("run_9", "p", "inspect_snapshot", {})
    assert after.outcome == Outcome.BLOCK and after.source == DecisionSource.ARMORIQ_TOKEN_ISSUANCE


def test_unreachable_issuance_is_unavailable_not_a_policy_block():
    gw = make_gw(FakeClient(exc=ConnectionError(f"cannot connect with {API_KEY}")))
    binding, decision = gw.bind_plan_with_decision(
        "run_9", grant(), [{"name": "inspect_snapshot", "args": {}}], "a@b.c"
    )
    assert binding.error and decision.outcome == Outcome.UNAVAILABLE
    assert API_KEY not in json.dumps(decision.model_dump(mode="json")) + binding.error
    assert gw.check("run_9", "p", "inspect_snapshot", {}).outcome == Outcome.UNAVAILABLE


def test_bind_plan_returns_only_the_binding():
    gw = make_gw(FakeClient(token=token()))
    b = gw.bind_plan("r", grant(), [{"name": "inspect_snapshot", "args": {}}], "a@b.c")
    assert b.plan_id == "plan_1"


def wider_client(check_result):
    client = FakeClient(token=token())
    orig = client.for_user

    def for_user(email):
        scope = orig(email)
        start = scope.start_session

        def start_session(opts):
            sess = start(opts)
            sess.result = check_result
            return sess

        scope.start_session = start_session
        return scope

    client.for_user = for_user
    return client


def test_probe_wider_plan_is_issued_then_blocked_by_the_org_allowlist():
    gw = make_gw(wider_client(er("block", False, "tool_not_in_allowlist", matched="cli-policy")))
    d = gw.probe_wider_plan("r", grant(), ["restore_access_grant"], "a@b.c")
    assert d.outcome == Outcome.BLOCK and d.source == DecisionSource.ARMORIQ_ENFORCE
    assert d.invariant == "org_policy_allowlist" and d.decisive
    assert "tool_not_in_allowlist" in d.reason
    assert d.sponsor.matched_policy == "cli-policy"
    assert d.sponsor.sanitized_response["issued"] is True
    assert d.evidence["wider_plan_blocked_at"] == "enforce"
    assert gw._client.sessions[-1].closed
    assert gw._client.sessions[-1].calls[0][0] == "restore_access_grant"


def test_probe_wider_plan_allow_only_when_issuance_and_enforcement_both_allow():
    gw = make_gw(wider_client(er("allow", True, "Allowed")))
    d = gw.probe_wider_plan("r", grant(), ["restore_access_grant"], "a@b.c")
    assert d.outcome == Outcome.ALLOW and d.invariant == "remint_wider_enforce_allowed"


def test_probe_wider_plan_check_exception_is_unavailable():
    client = wider_client(None)
    gw = make_gw(client)
    # session.check raises -> UNAVAILABLE, never ALLOW
    orig = client.for_user

    def for_user(email):
        scope = orig(email)
        start = scope.start_session

        def start_session(opts):
            sess = start(opts)
            sess.exc = RuntimeError("boom")
            return sess

        scope.start_session = start_session
        return scope

    client.for_user = for_user
    d = gw.probe_wider_plan("r", grant(), ["restore_access_grant"], "a@b.c")
    assert d.outcome == Outcome.UNAVAILABLE


def test_probe_wider_plan_issuance_refusal_is_still_recorded_as_an_issuance_block():
    from armoriq_sdk.exceptions import PolicyBlockedException

    refused = make_gw(
        FakeClient(
            exc=PolicyBlockedException(
                "x", reason="denied", metadata={"denied_tools": ["restore_access_grant"]}
            )
        )
    ).probe_wider_plan("r", grant(), ["restore_access_grant"], "a@b.c")
    assert refused.outcome == Outcome.BLOCK and refused.source == DecisionSource.ARMORIQ_TOKEN_ISSUANCE
    assert refused.evidence["wider_plan_blocked_at"] == "issuance"


def test_shadow_backend_check_reuses_wider_probe_evidence_per_run():
    gw2 = make_gw(wider_client(er("block", False, "tool_not_in_allowlist", matched="cli-policy")))
    gw2.attach_session_for_tests("r", FakeSession(), None)
    gw2.probe_wider_plan("r", grant(), ["restore_access_grant"], "a@b.c")
    sh = gw2.shadow_backend_check("r", "prp_1", "restore_access_grant", {})
    assert sh is not None and sh.shadow and not sh.decisive
    assert sh.source == DecisionSource.ARMORIQ_ENFORCE and sh.invariant == "org_policy_allowlist"
    assert sh.proposal_id == "prp_1"


def test_shadow_backend_check_mints_one_attacker_view_session_per_run():
    client = wider_client(er("block", False, "tool_not_in_allowlist", matched="cli-policy"))
    gw = make_gw(client)
    from rewindsafe.contracts import PlanBinding

    gw.attach_session_for_tests(
        "r", FakeSession(), PlanBinding(mode="live", simulated=False, plan_id="p", steps=TOOLS)
    )
    a = gw.shadow_backend_check("r", "p1", "restore_access_grant", {"tenant_id": "atlas"})
    b = gw.shadow_backend_check("r", "p2", "restore_access_grant", {"tenant_id": "atlas"})
    assert a is not None and b is not None and a.shadow and b.shadow
    assert len(client.sessions) == 1 and "would also have blocked" in a.reason
    gw.close_run("r", "blocked")
    assert client.sessions[0].closed


# ── enforcement classification (R1-08) ───────────────────────────────────


def test_default_deny_and_allowlist_are_distinguished():
    c = classify_enforce_result(er("block", False, "no_matching_policy"))
    assert c.invariant == "armoriq_default_deny" and "default-deny" in c.reason
    c = classify_enforce_result(er("block", False, "tool_not_in_allowlist"))
    assert c.invariant == "org_policy_allowlist"
    c = classify_enforce_result(er("allow", True, "Allowed by approved delegation d-1"))
    assert c.outcome == Outcome.ALLOW and c.invariant == "armoriq_delegation_consumed"


@pytest.mark.parametrize("code", [401, 429, 500, 503])
def test_http_errors_from_enforce_fail_closed_as_unavailable_not_policy_blocks(code):
    class S(FakeSession):
        def check(self, tool, args, user_email=None):
            gw._tls.enforce_status = code  # what the httpx response hook records
            return er("block", False, "Unauthorized")

    gw = gateway_with(S())
    d = gw.check("run_1", "p", "inspect_snapshot", {})
    assert d.outcome == Outcome.UNAVAILABLE and d.invariant == "enforcement_http_error"
    assert f"HTTP {code}" in d.reason


def test_403_remains_a_policy_block():
    class S(FakeSession):
        def check(self, tool, args, user_email=None):
            gw._tls.enforce_status = 403
            return er("block", False, "forbidden")

    gw = gateway_with(S())
    assert gw.check("run_1", "p", "inspect_snapshot", {}).outcome == Outcome.BLOCK


def test_default_deny_is_remembered_for_the_system_warning():
    gw = gateway_with(FakeSession(er("block", False, "no_matching_policy")))
    assert gw.describe()["default_deny_recent"] is False
    gw.check("run_1", "p", "inspect_snapshot", {})
    assert gw.describe()["default_deny_recent"] is True


# ── sponsor approval ─────────────────────────────────────────────────────


class DelegClient:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.executed: list = []
        self.polls = 0

    def get_delegation_status(self, delegation_id):
        self.polls += 1
        v = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if isinstance(v, Exception):
            raise v
        return v

    def mark_delegation_executed(self, *a, **k):  # the gateway must never call this
        self.executed.append(a)


def deleg_gw(statuses) -> tuple[LiveArmorIQGateway, DelegClient]:
    dc = DelegClient(statuses)
    gw = LiveArmorIQGateway(Settings(_env_file=None), client_factory=lambda: dc)
    from rewindsafe.contracts import PlanBinding

    gw.attach_session_for_tests(
        "run_1", FakeSession(), PlanBinding(mode="live", simulated=False, plan_id="plan_abc", steps=TOOLS)
    )
    return gw, dc


class DelegationErr(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("approved", "approved"),
        ("rejected", "rejected"),
        ("APPROVED", "timeout"),
        ("expired", "timeout"),
        ("none", "timeout"),
        (DelegationErr(404), "timeout"),
        (DelegationErr(401), "timeout"),
    ],
)
def test_await_sponsor_approval_compares_status_strings_exactly(status, expected):
    gw, dc = deleg_gw([status, "expired"])
    if status == "APPROVED":  # unknown status keeps polling until the deadline
        assert gw.await_sponsor_approval("run_1", "d1", 0.6) == "timeout"
    else:
        assert gw.await_sponsor_approval("run_1", "d1", 5.0) == expected
    assert dc.executed == []


def test_await_sponsor_approval_retries_transient_http_errors_then_approves():
    gw, dc = deleg_gw([DelegationErr(503), "pending", "approved"])
    assert gw.await_sponsor_approval("run_1", "d1", 20.0) == "approved"
    assert dc.polls == 3 and dc.executed == []


def test_await_sponsor_approval_without_session_is_not_an_approval():
    gw = LiveArmorIQGateway(Settings(_env_file=None), client_factory=lambda: SimpleNamespace())
    assert gw.await_sponsor_approval("none", "d", 1.0) == "timeout"


def test_await_sponsor_approval_honors_cancel():
    gw, _ = deleg_gw(["pending"])
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    assert gw.await_sponsor_approval("run_1", "d", 60.0, cancel) == "timeout"


def test_hold_approved_then_recheck_does_not_open_a_new_hold():
    hold = er("hold", False, "needs approval", delegation_id="deleg-9", matched="p")
    session = FakeSession(hold)
    dc = DelegClient(["approved"])
    gw = LiveArmorIQGateway(Settings(_env_file=None), client_factory=lambda: dc)
    from rewindsafe.contracts import PlanBinding

    gw.attach_session_for_tests(
        "run_1", session, PlanBinding(mode="live", simulated=False, plan_id="plan_abc", steps=TOOLS)
    )
    args = {"manifest_id": "m", "amount": 12400}
    first = gw.check("run_1", "p1", "apply_repair_manifest", args)
    assert first.outcome == Outcome.HOLD and first.sponsor.delegation_id == "deleg-9"
    assert gw.await_sponsor_approval("run_1", "deleg-9", 5.0) == "approved"
    # a DIFFERENT action is not covered by the approval
    other = gw.check("run_1", "p2", "apply_repair_manifest", {**args, "manifest_id": "other"})
    assert other.outcome == Outcome.HOLD
    # the SDK reuse path did not fire (still hold) -> approved delegation is honored exactly once
    again = gw.check("run_1", "p1", "apply_repair_manifest", args)
    assert again.outcome == Outcome.ALLOW and again.source == DecisionSource.ARMORIQ_APPROVAL
    assert again.invariant == "armoriq_delegation_consumed" and "deleg-9" in again.reason
    third = gw.check("run_1", "p1", "apply_repair_manifest", args)
    assert third.outcome == Outcome.HOLD  # single use
    assert dc.executed == []


def test_hold_approved_then_sdk_reuse_path_allows_by_delegation():
    session = FakeSession(er("hold", False, "needs approval", delegation_id="deleg-9"))
    dc = DelegClient(["approved"])
    gw = LiveArmorIQGateway(Settings(_env_file=None), client_factory=lambda: dc)
    from rewindsafe.contracts import PlanBinding

    gw.attach_session_for_tests(
        "run_1", session, PlanBinding(mode="live", simulated=False, plan_id="plan_abc", steps=TOOLS)
    )
    args = {"manifest_id": "m", "amount": 12400}
    gw.check("run_1", "p1", "apply_repair_manifest", args)
    gw.await_sponsor_approval("run_1", "deleg-9", 5.0)
    session.result = er("allow", True, "Allowed by approved delegation deleg-9")
    d = gw.check("run_1", "p1", "apply_repair_manifest", args)
    assert d.outcome == Outcome.ALLOW and d.invariant == "armoriq_delegation_consumed"
    assert d.source == DecisionSource.ARMORIQ_ENFORCE
    assert dc.executed == []


# ── plan lifecycle, observability, readiness ─────────────────────────────


class LifecycleSession(FakeSession):
    session_id = "sess-123"

    def __init__(self):
        super().__init__(er("allow", True, "ok"))
        self.generations: list[dict] = []
        self.flushed = False

    def record_generation(self, **kw):
        self.generations.append(kw)

    def flush_observability(self):
        self.flushed = True


class LifecycleClient:
    def __init__(self):
        self.completed: list[str] = []

    def complete_plan(self, plan_id):
        self.completed.append(plan_id)


def lifecycle_gw():
    client = LifecycleClient()
    gw = LiveArmorIQGateway(Settings(_env_file=None), client_factory=lambda: client)
    from rewindsafe.contracts import PlanBinding

    sess = LifecycleSession()
    gw.attach_session_for_tests(
        "run_1", sess, PlanBinding(mode="live", simulated=False, plan_id="plan_abc", steps=TOOLS)
    )
    return gw, client, sess


def test_close_run_completes_the_bound_plan_once_and_flushes_observability():
    gw, client, sess = lifecycle_gw()
    gw.close_run("run_1", "succeeded")
    assert client.completed == ["plan_abc"] and sess.flushed and sess.closed
    gw.close_run("run_1", "succeeded")  # idempotent: nothing left to complete
    assert client.completed == ["plan_abc"]


def test_close_run_without_outcome_completes_and_failed_runs_leave_the_plan_open():
    gw, client, _ = lifecycle_gw()
    gw.close_run("run_1")
    assert client.completed == ["plan_abc"]
    gw, client, sess = lifecycle_gw()
    gw.close_run("run_1", "failed")
    assert client.completed == [] and sess.closed


def test_close_run_never_raises_when_complete_plan_fails():
    gw, client, sess = lifecycle_gw()

    def boom(plan_id):
        raise RuntimeError("down")

    client.complete_plan = boom
    gw.close_run("run_1", "succeeded")
    assert sess.closed


def test_record_generation_reaches_the_session_and_never_raises():
    gw, _, sess = lifecycle_gw()
    gw.record_generation("run_1", "groq:openai/gpt-oss-120b", 120, 30, "stop")
    assert sess.generations == [
        {"model": "groq:openai/gpt-oss-120b", "input_tokens": 120, "output_tokens": 30, "finish_reason": "stop"}
    ]
    gw.record_generation("unknown-run", "m", 1, 1)  # no state: no-op


def test_bind_plan_records_latency_policies_and_observability_session():
    class Sess(FakeBindSession):
        session_id = "obs-sess-1"

    client = FakeClient(token=token())
    client.for_user = lambda email: SimpleNamespace(start_session=lambda opts: Sess(client, opts))
    gw = make_gw(client)
    b, d = gw.bind_plan_with_decision("r", grant(), [{"name": "inspect_snapshot", "args": {}}], "a@b.c", llm="groq:x")
    assert b.latency_ms is not None and b.matched_policies == ["p"]
    assert gw.observability_session_id("r") == "obs-sess-1"
    assert d.sponsor.sanitized_response["observability_session_id"] == "obs-sess-1"


def test_readiness_probe_verifies_with_one_plan_and_one_check():
    client = FakeClient(token=token())
    client.complete_plan = lambda plan_id: None
    client.for_user = lambda email: SimpleNamespace(
        start_session=lambda opts: _ready_session(client, opts)
    )
    gw = LiveArmorIQGateway(
        Settings(_env_file=None, ARMORIQ_API_KEY=API_KEY, ARMORIQ_USER_EMAIL="a@b.c"),
        client_factory=lambda: client,
    )
    r = gw.run_readiness_probe()
    assert r["state"] == "verified" and r["matched_policy"] == "cli-policy"
    assert r["plan_latency_ms"] is not None and r["check_latency_ms"] is not None
    assert not gw._runs  # synchronous probe cleaned up its own plan
    assert gw.readiness()["state"] in ("verified", "unverified")  # may start a background refresh
    if gw._readiness_thread is not None:
        gw._readiness_thread.join(timeout=5)
        assert not gw._readiness_thread.is_alive()
    assert not gw._runs


def _ready_session(client, opts):
    s = FakeBindSession(client, opts)
    s.result = er("allow", True, "ok", matched="cli-policy")
    return s


def test_readiness_failure_is_reported_never_raised():
    client = FakeClient(exc=RuntimeError("down"))
    gw = LiveArmorIQGateway(
        Settings(_env_file=None, ARMORIQ_API_KEY=API_KEY, ARMORIQ_USER_EMAIL="a@b.c"),
        client_factory=lambda: client,
    )
    r = gw.run_readiness_probe()
    assert r["state"] == "failed" and r["detail"]


def test_readiness_without_a_key_is_unverified():
    gw = LiveArmorIQGateway(Settings(_env_file=None), client_factory=lambda: None)
    assert gw.readiness()["state"] == "unverified"


def test_describe_never_includes_the_api_key():
    gw = LiveArmorIQGateway(Settings(_env_file=None, ARMORIQ_API_KEY=API_KEY), client_factory=lambda: None)
    info = gw.describe()
    assert info["mode"] == "live" and info["simulated"] is False and info["configured"] is True
    assert API_KEY not in json.dumps(info)
