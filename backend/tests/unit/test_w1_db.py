"""W1: database-backed behaviour of the authority runtime (own throwaway DB ``rs_dev_w1``).

Uses a minimal fake workflow adapter defined in this file, so the runtime is exercised
independently of the RewindSafe workflow. Skipped (not failed) when PostgreSQL is unreachable.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from rewindsafe.config import Settings
from rewindsafe.contracts import (
    Actor,
    ApprovalStatus,
    DecisionSource,
    DispatchStatus,
    GrantLimits,
    GrantStatus,
    Identity,
    InvariantCheck,
    InvariantStatus,
    Layer,
    Outcome,
    ProposalStatus,
    ScenarioSpec,
    TaskGrant,
    ToolKind,
    ToolSpec,
)
from rewindsafe.runtime import adapter as adapter_mod
from rewindsafe.runtime import approvals, db, events, grants, mutators, receipts
from rewindsafe.runtime.adapter import (
    AdmissionResult,
    ReviewRequirement,
    ToolContext,
    ToolExecution,
    make_decision,
)
from rewindsafe.runtime.armoriq_gateway import LiveArmorIQGateway, OfflineSimulatedGateway
from rewindsafe.runtime.canonical import digest, new_id, utcnow
from rewindsafe.runtime.dispatch import RunContext, dispatch
from rewindsafe.runtime.identities import IDENTITIES

ADMIN_DSN = os.environ.get(
    "REWINDSAFE_TEST_ADMIN_DSN", "postgresql://rewindsafe:rewindsafe@127.0.0.1:5433/postgres"
)
DB_NAME = f"rs_dev_w1_{os.getpid()}"
MAYA, DEV, SAM = IDENTITIES["maya"], IDENTITIES["dev"], IDENTITIES["sam"]
SECRET = "ak_live_SECRETSECRET123456"


# ─── fake workflow ───────────────────────────────────────────────────────


class FakeAdapter:
    workflow_id = "fake.workflow"
    mcp_name = "fake-mcp"

    def __init__(self, limits: GrantLimits | None = None) -> None:
        self.limits = limits or GrantLimits(max_commits=5, max_steps=20, approval_ttl_seconds=30)
        self.version = 1  # bump to simulate "state changed after approval"
        self.exec_calls: list[tuple[str, dict, Any]] = []
        self.review_threshold = 1000.0

    def tool_specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="read_item",
                title="Read item",
                description="Read an item",
                kind=ToolKind.READ,
                input_schema={
                    "type": "object",
                    "required": ["item_id"],
                    "properties": {"item_id": {"type": "string"}},
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                name="apply_repair_manifest",
                title="Apply",
                description="Apply an amount",
                kind=ToolKind.MUTATE,
                mutator=True,
                input_schema={
                    "type": "object",
                    "required": ["item_id", "amount"],
                    "properties": {"item_id": {"type": "string"}, "amount": {"type": "number"}},
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                name="admin_op",
                title="Admin",
                description="Privileged operation (never in a plan)",
                kind=ToolKind.ADMIN,
                mutator=True,
                input_schema={"type": "object", "additionalProperties": True},
            ),
        ]

    def scenarios(self) -> list[ScenarioSpec]:
        return []

    def build_grant(self, scenario: ScenarioSpec, identity: Identity, fixture_generation: int) -> TaskGrant:
        now = utcnow()
        return TaskGrant(
            grant_id="",  # the runtime assigns it
            workflow=self.workflow_id,
            scenario_id=scenario.scenario_id,
            principal=identity.identity_id,
            principal_email=identity.email,
            tenant_id=identity.tenant_id,
            purpose="fake task",
            allowed_tools=["read_item", "apply_repair_manifest"],
            resources={"item": ["I-1"]},
            limits=self.limits,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
            fixture_generation=fixture_generation,
            grant_digest="",
        )

    def plan_tool_calls(self, grant: TaskGrant) -> list[dict]:
        return [{"name": t, "args": {}} for t in grant.allowed_tools]

    def canonicalize(self, ctx: ToolContext, tool: str, args: dict) -> dict:
        return {**args, "tenant_id": ctx.grant.tenant_id}

    def check_grant(self, ctx: ToolContext, tool: str, args: dict) -> AdmissionResult:
        if tool not in ctx.grant.allowed_tools:
            return AdmissionResult(
                decision=make_decision(
                    ctx.run_id,
                    DecisionSource.GRANT_SCOPE,
                    Outcome.BLOCK,
                    f"{tool} is not granted",
                    invariant="tool_not_granted",
                )
            )
        if args.get("item_id") not in ctx.grant.resources["item"]:
            return AdmissionResult(
                decision=make_decision(
                    ctx.run_id,
                    DecisionSource.GRANT_SCOPE,
                    Outcome.BLOCK,
                    f"item {args.get('item_id')} is outside the grant",
                    invariant="resource_scope",
                )
            )
        return AdmissionResult()

    def validate(self, ctx: ToolContext, tool: str, args: dict) -> AdmissionResult:
        if tool == "apply_repair_manifest" and args["amount"] >= self.review_threshold:
            return AdmissionResult(
                review=ReviewRequirement(
                    reason="High-value apply needs a second reviewer",
                    targets=[args["item_id"]],
                    payload_digest=digest({"tool": tool, "args": args, "v": self.version}),
                    manifest_id=None,
                    state_constraints={"v": self.version},
                )
            )
        return AdmissionResult()

    def execute(self, ctx: ToolContext, tool: str, args: dict) -> ToolExecution:
        spec = next(s for s in self.tool_specs() if s.name == tool)
        if spec.mutator:
            mutators.record_entry(
                tool, run_id=ctx.run_id, proposal_id=ctx.proposal.proposal_id, via="dispatcher"
            )
            with db.autocommit_connection() as conn:
                conn.execute(
                    "UPDATE runtime.task_grants SET commits_used = commits_used + 1, "
                    "status = CASE WHEN commits_used + 1 >= max_commits THEN 'exhausted' ELSE status END "
                    "WHERE grant_id = %s",
                    (ctx.grant.grant_id,),
                )
        self.exec_calls.append((tool, args, ctx.approval))
        return ToolExecution(
            status=DispatchStatus.EXECUTED,
            observation={"ok": True, "tool": tool},
            summary=f"{tool} ok",
            state_changed=spec.mutator,
        )

    def protected_checks(self, tenant_id: str) -> list[InvariantCheck]:
        return [
            InvariantCheck(
                check_id="x:1", label="stays put", category="tombstone", status=InvariantStatus.PRESERVED
            )
        ]

    def app_state(self, tenant_id: str) -> dict:
        return {}


# ─── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def w1_db() -> Iterator[str]:
    try:
        admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    base = ADMIN_DSN.rpartition("/")[0]
    dsn = f"{base}/{DB_NAME}"
    with admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{DB_NAME}"')
    previous = db.dsn_override()
    db.reset_pool_for_tests(dsn)
    try:
        assert db.apply_migrations(dsn)
        with db.connection() as conn:
            conn.execute("INSERT INTO runtime.fixture_state (id, generation) VALUES (1, 1)")
        yield dsn
    finally:
        db.reset_pool_for_tests(previous)
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin2:
            admin2.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')


@pytest.fixture
def adapter() -> Iterator[FakeAdapter]:
    a = FakeAdapter()
    adapter_mod.register_adapter(a)
    yield a
    adapter_mod._registry.pop(a.workflow_id, None)


SCENARIO = ScenarioSpec(
    scenario_id="fake",
    workflow="fake.workflow",
    title="t",
    tagline="t",
    description="d",
    kind="baseline",
    order=1,
    grant_template={},
)


def make_ctx(adapter: FakeAdapter, identity: Identity = MAYA, gateway: Any = None) -> RunContext:
    draft = grants.create_draft(adapter, SCENARIO, identity)
    grant = grants.authorize(draft.grant_id, identity)
    run_id = new_id("run")
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO runtime.runs (run_id, grant_id, scenario_id, workflow, planner, planner_kind, enforcement_mode, "
            "status, fixture_generation, created_by) VALUES (%s,%s,'fake','fake.workflow','scripted','scripted','offline',"
            "'planning',%s,%s)",
            (run_id, grant.grant_id, grant.fixture_generation, identity.identity_id),
        )
    gw = gateway or OfflineSimulatedGateway(Settings(_env_file=None))
    gw.bind_plan(run_id, grant, adapter.plan_tool_calls(grant), identity.email)
    return RunContext(
        run_id=run_id,
        grant=grant,
        identity=identity,
        adapter=adapter,
        gateway=gw,
        scenario=SCENARIO,
        cancel=threading.Event(),
    )


def wait_for(fn, timeout: float = 15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("timed out waiting for condition")


def pending_for(rc: RunContext):
    return lambda: [a for a in approvals.list_for_tenant("atlas", "pending") if a.run_id == rc.run_id]


def start_dispatch(rc: RunContext, tool: str, args: dict, **kw) -> tuple[threading.Thread, dict]:
    box: dict = {}

    def run() -> None:
        box["outcome"] = dispatch(rc, tool, args, **kw)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, box


def decided(outcome, **match) -> list:
    return [d for d in outcome.decisions if all(getattr(d, k) == v for k, v in match.items())]


def set_grant_column(grant_id: str, sql: str, *params: Any) -> None:
    with db.connection() as conn:
        conn.execute(f"UPDATE runtime.task_grants SET {sql} WHERE grant_id = %s", (*params, grant_id))


# ─── migrations, events, mutators ───────────────────────────────────────


def test_migrations_are_tracked_and_idempotent(w1_db):
    assert db.apply_migrations(w1_db) == []
    with db.connection() as conn:
        names = [r["filename"] for r in conn.execute("SELECT filename FROM runtime.schema_migrations")]
    assert "001_schema.sql" in names


def test_events_emit_list_order_after_seq_and_redaction():
    rid = new_id("run")
    d = make_decision(rid, DecisionSource.GRANT_SCOPE, Outcome.BLOCK, "nope", decisive=True)
    e1 = events.emit(rid, "agent.note", Actor.AGENT, "hello", "first", data={"api_key": SECRET, "ok": 1})
    e2 = events.emit(rid, "decision", Actor.REWINDSAFE, "blocked", f"leak {SECRET}", decision=d)
    events.emit(rid, "agent.note", Actor.AGENT, "third")
    assert e2.seq > e1.seq and e1.data == {"api_key": "[redacted]", "ok": 1}
    listed = events.list_events(rid)
    assert [e.title for e in listed] == ["hello", "blocked", "third"]
    assert listed[1].decision.decision_id == d.decision_id and SECRET not in listed[1].detail
    assert [e.title for e in events.list_events(rid, after_seq=e1.seq)] == ["blocked", "third"]
    assert len(events.list_events(rid, limit=1)) == 1
    with pytest.raises(ValueError):
        events.emit(rid, "made.up", Actor.SYSTEM, "x")


def test_events_survive_a_rolled_back_business_transaction():
    rid = new_id("run")
    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.execute("CREATE TEMP TABLE t(x int)")
        events.emit(rid, "agent.note", Actor.SYSTEM, "visible despite rollback")
        raise RuntimeError("boom")
    assert [e.title for e in events.list_events(rid)] == ["visible despite rollback"]


def test_mutator_entries_record_and_count():
    rid = new_id("run")
    assert mutators.count_entries("admin_op", run_id=rid) == 0
    before_all = mutators.count_entries("admin_op")
    mutators.record_entry("admin_op", run_id=rid, proposal_id="prp_1", via="test")
    mutators.record_entry("admin_op", run_id=None, proposal_id=None, via="operator_admin")
    assert mutators.count_entries("admin_op", run_id=rid) == 1
    assert mutators.count_entries("admin_op") == before_all + 2
    assert mutators.count_entries("never_called", run_id=rid) == 0


# ─── grants ──────────────────────────────────────────────────────────────


def test_grant_lifecycle_create_authorize_load(adapter):
    draft = grants.create_draft(adapter, SCENARIO, MAYA)
    assert draft.status == GrantStatus.DRAFT and draft.grant_id.startswith("grt_")
    assert draft.grant_digest == grants.compute_grant_digest(draft) and draft.fixture_generation == 1
    assert grants.load(draft.grant_id).status == GrantStatus.DRAFT

    with pytest.raises(grants.GrantPermissionError):
        grants.authorize(draft.grant_id, SAM)  # not the principal (and another tenant)
    with pytest.raises(grants.GrantPermissionError):
        grants.authorize(draft.grant_id, DEV)  # same tenant, still not the principal

    active = grants.authorize(draft.grant_id, MAYA)
    assert active.status == GrantStatus.ACTIVE and active.authorized_by == "maya" and active.authorized_at
    assert timedelta(minutes=29) < active.expires_at - utcnow() <= timedelta(minutes=30)
    assert active.grant_digest == grants.compute_grant_digest(active) != draft.grant_digest
    with pytest.raises(grants.GrantStateError):
        grants.authorize(draft.grant_id, MAYA)  # already active
    with pytest.raises(grants.GrantNotFound):
        grants.load("grt_missing")

    # lifecycle columns are overlaid on the body
    set_grant_column(draft.grant_id, "commits_used = 1, status = 'exhausted'")
    reloaded = grants.load(draft.grant_id)
    assert reloaded.commits_used == 1 and reloaded.status == GrantStatus.EXHAUSTED
    assert (
        grants.lifecycle_check(reloaded, grants.current_generation(), tool_is_mutator=True).invariant
        == "grant_exhausted"
    )


def test_authorize_refuses_a_draft_from_an_older_fixture_generation(adapter):
    draft = grants.create_draft(adapter, SCENARIO, MAYA)
    with db.connection() as conn:
        conn.execute("UPDATE runtime.fixture_state SET generation = 2")
    try:
        assert grants.current_generation() == 2
        with pytest.raises(grants.GrantStateError, match="reset"):
            grants.authorize(draft.grant_id, MAYA)
    finally:
        with db.connection() as conn:
            conn.execute("UPDATE runtime.fixture_state SET generation = 1")


# ─── dispatcher: admission layers ───────────────────────────────────────


def test_allowed_read_executes_and_is_fully_recorded(adapter):
    rc = make_ctx(adapter)
    out = dispatch(rc, "read_item", {"item_id": "I-1"}, rationale=f"look, key {SECRET}")
    assert out.status == DispatchStatus.EXECUTED and out.observation["ok"] is True
    assert (
        out.proposal.status == ProposalStatus.EXECUTED and out.proposal.step_index == 0 and rc.step_index == 1
    )
    armor = decided(out, layer=Layer.ARMORIQ)
    assert (
        len(armor) == 1 and armor[0].outcome == Outcome.ALLOW and armor[0].simulated and not armor[0].decisive
    )
    evs = events.list_events(rc.run_id)
    types = [e.type for e in evs]
    assert types[0] == "agent.proposal" and "decision" in types and "tool.result" in types
    assert types.count("telemetry.delivery") == 1
    assert SECRET not in json.dumps([e.model_dump(mode="json") for e in evs])
    with db.connection() as conn:
        assert (
            conn.execute(
                "SELECT status FROM runtime.proposals WHERE proposal_id=%s", (out.proposal.proposal_id,)
            ).fetchone()["status"]
            == "executed"
        )
        body = conn.execute(
            "SELECT body FROM runtime.decisions WHERE decision_id=%s", (armor[0].decision_id,)
        ).fetchone()["body"]
        assert body["source"] == "armoriq.offline_simulation" and body["simulated"] is True
        assert (
            conn.execute("SELECT steps_used FROM runtime.runs WHERE run_id=%s", (rc.run_id,)).fetchone()[
                "steps_used"
            ]
            == 1
        )
        assert (
            conn.execute(
                "SELECT status FROM runtime.telemetry_outbox WHERE run_id=%s", (rc.run_id,)
            ).fetchone()["status"]
            == "skipped"
        )


def test_unknown_tool_and_bad_arguments_stop_at_the_runtime_layer(adapter):
    rc = make_ctx(adapter)
    for tool, args, invariant in [
        ("drop_database", {}, "unknown_tool"),
        ("read_item", {}, "schema_violation"),
        ("read_item", {"item_id": 7}, "schema_violation"),
        ("read_item", {"item_id": "I-1", "sql": "DROP TABLE x"}, "schema_violation"),
    ]:
        out = dispatch(rc, tool, args)
        assert out.status == DispatchStatus.BLOCKED and out.decisions[-1].invariant == invariant
        assert (
            out.decisions[-1].source == DecisionSource.TOOL_REGISTRY
            and out.decisions[-1].layer == Layer.RUNTIME
        )
        assert (
            out.observation["status"] == "blocked"
            and out.observation["blocked_by"] == "rewindsafe.tool_registry"
        )
        assert out.observation["guidance"].startswith("Do not retry this action")
    assert adapter.exec_calls == []
    out = dispatch(rc, "read_item", ["not", "an", "object"])  # type: ignore[arg-type]
    assert out.status == DispatchStatus.BLOCKED


def test_off_plan_privileged_tool_is_blocked_by_armoriq_with_a_shadow_grant_decision(adapter):
    rc = make_ctx(adapter)
    out = dispatch(rc, "admin_op", {"what": "restore"}, source="boundary_harness")
    assert out.status == DispatchStatus.BLOCKED and out.proposal.status == ProposalStatus.BLOCKED
    decisive = decided(out, decisive=True)
    assert len(decisive) == 1 and decisive[0].layer == Layer.ARMORIQ and decisive[0].simulated
    assert decisive[0].reason.startswith("tool-not-in-plan")
    shadow = decided(out, shadow=True)
    assert (
        len(shadow) == 1
        and shadow[0].layer == Layer.GRANT
        and shadow[0].invariant == "tool_not_granted"
        and not shadow[0].decisive
    )
    assert out.observation["blocked_by"] == "armoriq.offline_simulation"
    assert adapter.exec_calls == [] and mutators.count_entries("admin_op", run_id=rc.run_id) == 0
    evs = events.list_events(rc.run_id)
    assert evs[0].type == "agent.proposal" and evs[0].actor == Actor.HARNESS
    titles = [e.title for e in evs]
    assert "Simulated ArmorIQ blocked admin_op" in titles
    assert any("would also have blocked" in t for t in titles)
    block_event = next(e for e in evs if e.title == "Simulated ArmorIQ blocked admin_op")
    assert "Not in the signed recovery plan" in block_event.detail and "never entered" in block_event.detail


def test_grant_scope_blocks_before_anything_runs(adapter):
    rc = make_ctx(adapter)
    out = dispatch(rc, "read_item", {"item_id": "I-999"})
    assert out.status == DispatchStatus.BLOCKED
    d = decided(out, decisive=True)[0]
    assert (
        d.layer == Layer.GRANT and d.invariant == "resource_scope" and d.source == DecisionSource.GRANT_SCOPE
    )
    assert out.observation["blocked_by"] == "rewindsafe.grant_scope" and adapter.exec_calls == []


def test_enforcement_unavailable_fails_closed(adapter):
    rc = make_ctx(adapter)
    rc.gateway.force_unavailable(True)
    out = dispatch(rc, "read_item", {"item_id": "I-1"})
    assert out.status == DispatchStatus.UNAVAILABLE and out.proposal.status == ProposalStatus.UNAVAILABLE
    d = decided(out, decisive=True)[0]
    assert d.outcome == Outcome.UNAVAILABLE and d.layer == Layer.ARMORIQ
    assert out.observation["status"] == "unavailable" and "fail closed" in out.observation["guidance"]
    assert adapter.exec_calls == []
    rc.gateway.force_unavailable(False)
    assert dispatch(rc, "read_item", {"item_id": "I-1"}).status == DispatchStatus.EXECUTED


def test_broken_gateway_and_broken_adapter_checks_fail_closed(adapter):
    rc = make_ctx(adapter)

    class Exploding:
        mode = "offline"

        def check(self, *a, **k):
            raise RuntimeError("gateway exploded")

    rc.gateway = Exploding()  # type: ignore[assignment]
    out = dispatch(rc, "read_item", {"item_id": "I-1"})
    assert out.status == DispatchStatus.UNAVAILABLE and adapter.exec_calls == []

    rc2 = make_ctx(adapter)
    adapter.check_grant = lambda *a, **k: (_ for _ in ()).throw(ValueError("bug"))  # type: ignore[method-assign]
    out2 = dispatch(rc2, "read_item", {"item_id": "I-1"})
    assert (
        out2.status == DispatchStatus.BLOCKED
        and decided(out2, decisive=True)[0].invariant == "grant_check_error"
    )
    assert adapter.exec_calls == []


def test_an_adapter_cannot_issue_a_decision_labeled_as_armoriq(adapter):
    rc = make_ctx(adapter)
    adapter.check_grant = lambda ctx, tool, args: AdmissionResult(  # type: ignore[method-assign]
        decision=make_decision(ctx.run_id, DecisionSource.ARMORIQ_ENFORCE, Outcome.ALLOW, "trust me")
    )
    out = dispatch(rc, "read_item", {"item_id": "I-1"})
    assert (
        out.status == DispatchStatus.BLOCKED
        and decided(out, decisive=True)[0].invariant == "mislabeled_decision"
    )


# ─── lifecycle ───────────────────────────────────────────────────────────


def test_expired_revoked_tampered_and_exhausted_grants_are_blocked(adapter):
    rc = make_ctx(adapter)
    set_grant_column(rc.grant.grant_id, "expires_at = now() - interval '1 minute'")
    out = dispatch(rc, "read_item", {"item_id": "I-1"})
    assert (
        out.status == DispatchStatus.BLOCKED and decided(out, decisive=True)[0].invariant == "grant_expired"
    )

    rc = make_ctx(adapter)
    grants.revoke(rc.grant.grant_id)
    assert (
        decided(dispatch(rc, "read_item", {"item_id": "I-1"}), decisive=True)[0].invariant == "grant_inactive"
    )

    rc = make_ctx(adapter)
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="scope is frozen"), db.connection() as conn:
        conn.execute(
            'UPDATE runtime.task_grants SET body = jsonb_set(body, \'{allowed_tools}\', \'["read_item","apply_repair_manifest","admin_op"]\') WHERE grant_id = %s',
            (rc.grant.grant_id,),
        )
    # migration 006 refuses the scope rewrite itself, so tamper with the stored digest instead
    set_grant_column(rc.grant.grant_id, "grant_digest = %s", "sha256:forged")
    assert (
        decided(dispatch(rc, "read_item", {"item_id": "I-1"}), decisive=True)[0].invariant == "grant_tampered"
    )

    adapter.limits = GrantLimits(max_commits=1, approval_ttl_seconds=30)
    rc = make_ctx(adapter)
    assert (
        dispatch(rc, "apply_repair_manifest", {"item_id": "I-1", "amount": 10}).status
        == DispatchStatus.EXECUTED
    )
    second = dispatch(rc, "apply_repair_manifest", {"item_id": "I-1", "amount": 11})
    assert (
        second.status == DispatchStatus.BLOCKED
        and decided(second, decisive=True)[0].invariant == "grant_exhausted"
    )
    assert (
        dispatch(rc, "read_item", {"item_id": "I-1"}).status == DispatchStatus.EXECUTED
    )  # receipts stay readable
    assert len(adapter.exec_calls) == 2


def test_step_budget_and_cancellation(adapter):
    adapter.limits = GrantLimits(max_steps=2, approval_ttl_seconds=30)
    rc = make_ctx(adapter)
    assert dispatch(rc, "read_item", {"item_id": "I-1"}).status == DispatchStatus.EXECUTED
    assert dispatch(rc, "read_item", {"item_id": "I-1"}).status == DispatchStatus.EXECUTED
    third = dispatch(rc, "read_item", {"item_id": "I-1"})
    assert (
        third.status == DispatchStatus.BLOCKED and decided(third, decisive=True)[0].invariant == "step_budget"
    )

    adapter.limits = GrantLimits(approval_ttl_seconds=30)
    rc2 = make_ctx(adapter)
    rc2.cancel.set()
    out = dispatch(rc2, "read_item", {"item_id": "I-1"})
    assert (
        out.status == DispatchStatus.BLOCKED and decided(out, decisive=True)[0].invariant == "run_cancelled"
    )


# ─── dispatcher: approvals ──────────────────────────────────────────────


HIGH = {"item_id": "I-1", "amount": 12400}


def test_high_value_apply_needs_a_second_reviewer_and_is_revalidated(adapter):
    rc = make_ctx(adapter)
    t, box = start_dispatch(rc, "apply_repair_manifest", HIGH)
    (appr,) = wait_for(pending_for(rc))
    assert appr.status == ApprovalStatus.PENDING and appr.requested_by == "maya" and appr.targets == ["I-1"]
    assert appr.state_constraints == {"v": 1}
    assert adapter.exec_calls == []  # nothing runs while held

    def run_status() -> str:
        with db.connection() as conn:
            return conn.execute("SELECT status FROM runtime.runs WHERE run_id=%s", (rc.run_id,)).fetchone()[
                "status"
            ]

    wait_for(lambda: run_status() == "awaiting_approval")

    for who, code in [(MAYA, "reviewer_role_required"), (SAM, "reviewer_role_required")]:
        with pytest.raises(approvals.ApprovalError) as ei:
            approvals.decide(appr.approval_id, who, "approve")
        assert ei.value.code == code
    assert approvals.get(appr.approval_id).status == ApprovalStatus.PENDING

    done = approvals.decide(appr.approval_id, DEV, "approve", note="looks right")
    assert done.status == ApprovalStatus.APPROVED and done.decided_by == "dev"
    with pytest.raises(approvals.ApprovalError) as ei:
        approvals.decide(appr.approval_id, DEV, "reject")
    assert ei.value.code == "not_pending"

    t.join(20)
    out = box["outcome"]
    assert out.status == DispatchStatus.EXECUTED and len(adapter.exec_calls) == 1
    executed_with = adapter.exec_calls[0][2]
    assert (
        executed_with is not None
        and executed_with.approval_id == appr.approval_id
        and executed_with.status == ApprovalStatus.APPROVED
    )
    # offline simulation mirrors live: no sponsor HOLD, so there is no sponsor delegation to wait for
    assert out.approval.sponsor_status is None
    # approval never immunizes: lifecycle/ArmorIQ/grant/domain ran twice
    armor = decided(out, layer=Layer.ARMORIQ)
    assert [d.outcome for d in armor] == [Outcome.ALLOW, Outcome.ALLOW]
    evs = events.list_events(rc.run_id)
    types = [e.type for e in evs]
    assert "approval.requested" in types and "approval.resolved" in types
    assert any("re-check after approval" in e.title for e in evs)
    assert next(e for e in evs if e.type == "approval.resolved").actor == Actor.REVIEWER
    with db.connection() as conn:
        assert (
            conn.execute("SELECT status FROM runtime.runs WHERE run_id=%s", (rc.run_id,)).fetchone()["status"]
            == "planning"
        )


def test_requester_cannot_approve_their_own_action(adapter):
    rc = make_ctx(adapter, identity=DEV)  # a reviewer who is also the requester
    t, box = start_dispatch(rc, "apply_repair_manifest", HIGH)
    (appr,) = wait_for(pending_for(rc))
    with pytest.raises(approvals.ApprovalError) as ei:
        approvals.decide(appr.approval_id, DEV, "approve")
    assert ei.value.code == "separation_of_duties"
    approvals.decide(appr.approval_id, DEV.model_copy(update={"identity_id": "dev2"}), "reject")
    t.join(20)
    assert box["outcome"].status == DispatchStatus.HELD_REJECTED and adapter.exec_calls == []


def test_rejected_approval_changes_nothing(adapter):
    rc = make_ctx(adapter)
    t, box = start_dispatch(rc, "apply_repair_manifest", HIGH)
    (appr,) = wait_for(pending_for(rc))
    approvals.decide(appr.approval_id, DEV, "reject", note="amount looks wrong")
    t.join(20)
    out = box["outcome"]
    assert out.status == DispatchStatus.HELD_REJECTED and out.proposal.status == ProposalStatus.REJECTED
    d = decided(out, decisive=True)[0]
    assert d.layer == Layer.APPROVAL and d.invariant == "approval_rejected" and "Orion" in d.reason
    assert adapter.exec_calls == [] and mutators.count_entries("apply_repair_manifest", run_id=rc.run_id) == 0
    assert out.observation["status"] == "rejected" and out.observation["blocked_by"] == "rewindsafe.approval"


def test_state_change_after_approval_blocks_execution_payload_substitution(adapter):
    rc = make_ctx(adapter)
    t, box = start_dispatch(rc, "apply_repair_manifest", HIGH)
    (appr,) = wait_for(pending_for(rc))
    adapter.version = 2  # authority/state moved after the reviewer saw v1
    try:
        approvals.decide(appr.approval_id, DEV, "approve")
        t.join(20)
    finally:
        adapter.version = 1
    out = box["outcome"]
    assert out.status == DispatchStatus.BLOCKED and adapter.exec_calls == []
    d = decided(out, decisive=True)[0]
    assert d.layer == Layer.APPROVAL and d.invariant == "payload_changed_after_approval"
    assert d.evidence["approved_digest"] != d.evidence["current_digest"]


def test_approval_expires_if_nobody_decides(adapter):
    adapter.limits = GrantLimits(approval_ttl_seconds=1)
    rc = make_ctx(adapter)
    out = dispatch(rc, "apply_repair_manifest", HIGH)
    assert out.status == DispatchStatus.HELD_REJECTED and adapter.exec_calls == []
    assert decided(out, decisive=True)[0].invariant == "approval_expired"
    assert out.approval.status == ApprovalStatus.EXPIRED
    with pytest.raises(approvals.ApprovalError) as ei:
        approvals.decide(out.approval.approval_id, DEV, "approve")
    assert ei.value.code == "not_pending"
    assert any(
        e.type == "approval.resolved" and e.actor == Actor.REWINDSAFE for e in events.list_events(rc.run_id)
    )


def test_fixture_reset_cancels_pending_approvals_and_the_waiting_dispatch(adapter):
    rc = make_ctx(adapter)
    t, box = start_dispatch(rc, "apply_repair_manifest", HIGH)
    (appr,) = wait_for(pending_for(rc))
    assert approvals.cancel_pending_for_generation(1) >= 1
    t.join(20)
    out = box["outcome"]
    assert out.status == DispatchStatus.HELD_REJECTED and adapter.exec_calls == []
    assert approvals.get(appr.approval_id).status == ApprovalStatus.CANCELLED
    assert decided(out, decisive=True)[0].invariant == "run_cancelled"


def test_run_cancellation_while_waiting_for_approval(adapter):
    rc = make_ctx(adapter)
    t, box = start_dispatch(rc, "apply_repair_manifest", HIGH)
    wait_for(pending_for(rc))
    rc.cancel.set()
    t.join(20)
    assert box["outcome"].status == DispatchStatus.HELD_REJECTED and adapter.exec_calls == []


# ─── gateway persistence, receipts, metrics ─────────────────────────────


def test_live_gateway_report_tracks_delivery_honestly(adapter):
    class Sess:
        def __init__(self, gw_ref, status):
            self.gw_ref, self.status = gw_ref, status

        def report(self, tool, args, result, opts):
            if self.status is not None:
                self.gw_ref[0]._tls.audit_status = self.status

    ref: list = []
    gw = LiveArmorIQGateway(Settings(_env_file=None), client_factory=lambda: SimpleNamespace())
    ref.append(gw)
    cases = [("a1", 200, "delivered"), ("a2", 500, "failed"), ("a3", None, "failed")]
    for run_id, http, expected in cases:
        gw.attach_session_for_tests(run_id, Sess(ref, http))
        gw.report(
            run_id,
            "prp_1",
            "apply_repair_manifest",
            {"item_id": "I-1", "api_key": SECRET},
            {"summary": "ok"},
            "success",
        )
        with db.connection() as conn:
            row = conn.execute(
                "SELECT status, attempts, last_error, payload FROM runtime.telemetry_outbox WHERE run_id=%s",
                (run_id,),
            ).fetchone()
        assert row["status"] == expected and row["attempts"] == 1
        assert SECRET not in json.dumps(row["payload"])
        assert (row["last_error"] is None) == (expected == "delivered")
        assert events.list_events(run_id)[0].data["status"] == expected
    gw.report("no-session", "p", "t", {}, {}, "success")
    with db.connection() as conn:
        assert (
            conn.execute("SELECT status FROM runtime.telemetry_outbox WHERE run_id='no-session'").fetchone()[
                "status"
            ]
            == "failed"
        )


def test_metrics_and_evidence_are_honest_and_secret_free(adapter):
    rc = make_ctx(adapter)
    dispatch(rc, "read_item", {"item_id": "I-1"}, rationale=f"key {SECRET}")
    dispatch(rc, "admin_op", {})  # blocked by ArmorIQ (simulated)
    dispatch(rc, "read_item", {"item_id": "I-77"})  # blocked by grant scope
    dispatch(rc, "apply_repair_manifest", {"item_id": "I-1", "amount": 10})
    rc.gateway.force_unavailable(True)
    dispatch(rc, "read_item", {"item_id": "I-1"})
    rc.gateway.force_unavailable(False)
    events.emit(rc.run_id, "replan", Actor.AGENT, "replanning", data={"reason": "blocked", "attempt": 1})

    m = receipts.run_metrics(rc.run_id)
    assert m["proposals"] == 5 and m["executed"] == 2
    assert m["blocked_by_layer"] == {
        "armoriq": 0,
        "armoriq_simulated": 1,
        "grant": 1,
        "domain": 0,
        "postgres": 0,
        "approval": 0,
        "runtime": 0,
    }
    assert m["enforcement_unavailable"] == 1 and m["replans"] == 1
    assert m["prohibited_handler_entries"] == 0 and m["forbidden_effects_observed"] == 0
    assert (
        m["simulated"] is True
        and m["armoriq_latency_ms"]["count"] == 0
        and m["armoriq_latency_ms"]["simulated_count"] >= 4
    )
    assert m["end_to_end_ms"] >= 0

    mutators.record_entry("admin_op", run_id=rc.run_id, proposal_id=None, via="test")
    m2 = receipts.run_metrics(rc.run_id)
    assert m2["prohibited_handler_entries"] == 1 and m2["forbidden_effects_observed"] == 1

    ev = receipts.build_evidence(rc.run_id)
    for key in (
        "exported_at",
        "contract_version",
        "source_commit",
        "run",
        "grant",
        "plan",
        "proposals",
        "events",
        "mutator_entries",
        "protected_checks",
        "metrics",
        "telemetry",
        "fixture",
        "disclaimers",
    ):
        assert key in ev, key
    assert ev["contract_version"] == "1.0" and ev["source_commit"]
    assert len(ev["proposals"]) == 5 and ev["proposals"][1]["decisions"]
    assert ev["protected_checks"]["checks"][0]["check_id"] == "x:1"
    assert ev["mutator_entries"]["by_handler"] == {"apply_repair_manifest": 1, "admin_op": 1}
    assert any("SIMULATED" in n and "not sponsor enforcement evidence" in n for n in ev["disclaimers"])
    assert any("binds tool names to the signed plan" in n for n in ev["disclaimers"])
    assert ev["fixture"]["generation"] == 1
    dumped = json.dumps(ev)
    assert SECRET not in dumped and "ak_live_" not in dumped

    g = receipts.global_metrics()
    assert g["runs"] >= 1 and g["fixture_generation"] == 1 and g["enforcement_modes"]["offline"] >= 1
    assert set(g["blocked_by_layer"]) == {"armoriq", "armoriq_simulated", "grant", "domain", "postgres", "approval", "runtime"}
    assert g["forbidden_effects_observed"] >= 1  # the admin_op entry recorded above
    assert digest(g)  # JSON-canonicalizable


# ─── P1b fixes ───────────────────────────────────────────────────────────


class RecordingGateway(OfflineSimulatedGateway):
    def __init__(self) -> None:
        super().__init__(Settings(_env_file=None))
        self.reports: list[tuple] = []

    def report(self, run_id, proposal_id, tool, args, result_summary, status):
        self.reports.append((tool, args, result_summary, status))
        super().report(run_id, proposal_id, tool, args, result_summary, status)


def test_approval_whose_review_requirement_vanishes_fails_closed(adapter):
    orig = adapter.validate
    calls = {"n": 0}

    def flaky(ctx, tool, args):
        calls["n"] += 1
        return orig(ctx, tool, args) if calls["n"] == 1 else AdmissionResult()

    adapter.validate = flaky
    rc = make_ctx(adapter)
    t, box = start_dispatch(rc, "apply_repair_manifest", HIGH)
    (appr,) = wait_for(pending_for(rc))
    approvals.decide(appr.approval_id, DEV, "approve")
    t.join(20)
    out = box["outcome"]
    assert out.status == DispatchStatus.BLOCKED and adapter.exec_calls == []
    d = decided(out, decisive=True)[-1]
    assert d.layer == Layer.APPROVAL and d.invariant == "approval_context_changed"


def test_audit_reports_use_canonical_args_and_cover_blocked_attempts(adapter):
    gw = RecordingGateway()
    rc = make_ctx(adapter, gateway=gw)
    dispatch(rc, "read_item", {"item_id": "I-1"})
    ok = [r for r in gw.reports if r[3] == "success"]
    assert len(ok) == 1
    assert ok[0][1].get("tenant_id") == rc.grant.tenant_id  # canonical (server-derived) args
    assert ok[0][2]["duration_ms"] >= 0
    # ArmorIQ allowed the call, the grant layer then blocked it: still reported, never as success
    dispatch(rc, "read_item", {"item_id": "I-77"})
    blocked = [r for r in gw.reports if r[3] == "failed"]
    assert len(blocked) == 1
    assert blocked[0][2]["summary"] == "blocked attempt (not executed)"
    assert blocked[0][2]["blocked_by"] == "rewindsafe.grant_scope"
    assert blocked[0][1].get("tenant_id") == rc.grant.tenant_id
    # an off-plan call blocked by ArmorIQ itself is ArmorIQ's own row: not re-reported
    dispatch(rc, "admin_op", {})
    assert len([r for r in gw.reports if r[3] == "failed"]) == 1


def test_approved_action_report_names_the_reviewer(adapter):
    gw = RecordingGateway()
    rc = make_ctx(adapter, gateway=gw)
    t, box = start_dispatch(rc, "apply_repair_manifest", HIGH)
    (appr,) = wait_for(pending_for(rc))
    approvals.decide(appr.approval_id, DEV, "approve")
    t.join(20)
    assert box["outcome"].status == DispatchStatus.EXECUTED
    (rep_,) = [r for r in gw.reports if r[3] == "success"]
    assert rep_[2]["approved_by"] == DEV.name and rep_[2]["approved_by_email"] == DEV.email


def test_grants_close_marks_active_grant_exhausted_once(adapter):
    rc = make_ctx(adapter)
    closed = grants.close(rc.grant.grant_id, "run finished")
    assert closed.status == GrantStatus.EXHAUSTED
    assert grants.close(rc.grant.grant_id, "again").status == GrantStatus.EXHAUSTED
    out = dispatch(rc, "apply_repair_manifest", {"item_id": "I-1", "amount": 1})
    assert out.status == DispatchStatus.BLOCKED and adapter.exec_calls == []
    rc2 = make_ctx(adapter)
    grants.revoke(rc2.grant.grant_id)
    assert grants.close(rc2.grant.grant_id).status == GrantStatus.REVOKED  # only ACTIVE grants close


def test_groq_keys_are_redacted():
    from rewindsafe.runtime.canonical import redact_secrets, redact_text

    key = "gsk_" + "a1B2c3D4e5F6g7H8i9J0k1L2"
    assert key not in redact_text(f"401 from groq: bad key {key}")
    out = redact_secrets({"groq_api_key": key, "note": f"x {key}"})
    assert key not in json.dumps(out)


def test_events_are_serialized_per_run_and_gapless():
    run_id = new_id("run")
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(10):
                events.emit(run_id, "agent.note", Actor.AGENT, f"w{n}-{i}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    ts = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert not errors
    evs = events.list_events(run_id)
    assert len(evs) == 40
    seqs = [e.seq for e in evs]
    assert seqs == sorted(seqs) and len(set(seqs)) == 40


def test_latency_split_separates_enforce_issuance_local_and_simulated():
    from rewindsafe.contracts import Decision  # noqa: F401
    from rewindsafe.runtime.receipts import _armoriq_split, _blocked_by_layer

    def dec(src, outcome, lat=None, **kw):
        return adapter_mod.make_decision("r", src, outcome, "x", latency_ms=lat, **kw)

    ds = [
        dec(DecisionSource.ARMORIQ_ENFORCE, Outcome.ALLOW, 800.0),
        dec(DecisionSource.ARMORIQ_ENFORCE, Outcome.BLOCK, 900.0, decisive=True),
        dec(DecisionSource.ARMORIQ_TOKEN_ISSUANCE, Outcome.ALLOW, 4700.0),
        dec(DecisionSource.ARMORIQ_PLAN_BINDING, Outcome.BLOCK, 0.0, decisive=True),
        dec(DecisionSource.ARMORIQ_SIMULATED, Outcome.BLOCK, None, decisive=True, simulated=True),
    ]
    split = _armoriq_split(ds)
    assert split["enforce"]["count"] == 2 and split["enforce"]["p50"] == 850.0
    assert split["issuance"] == {"p50": 4700.0, "p95": 4700.0, "count": 1}
    assert split["plan_binding"] == {"count": 1} and split["simulated_count"] == 1
    layers = _blocked_by_layer(ds)
    assert layers["armoriq"] == 2 and layers["armoriq_simulated"] == 1


def test_record_decision_persists_plan_issuance_with_plain_copy(adapter):
    rc = make_ctx(adapter)
    d = adapter_mod.make_decision(
        rc.run_id,
        DecisionSource.ARMORIQ_TOKEN_ISSUANCE,
        Outcome.ALLOW,
        "Plan issued: 2 tools allowed",
        latency_ms=4700.0,
    )
    from rewindsafe.runtime.dispatch import record_decision

    record_decision(d, tool="plan")
    ev = [e for e in events.list_events(rc.run_id) if e.type == "decision"][-1]
    assert ev.title == "ArmorIQ issued a signed intent plan"
    ev_json = receipts.build_evidence(rc.run_id)
    assert any(x["source"] == DecisionSource.ARMORIQ_TOKEN_ISSUANCE.value for x in ev_json["run_decisions"])


# ─── migrations: adoption and discovery ─────────────────────────────────


@contextmanager
def _scratch_database(suffix: str) -> Iterator[str]:
    name = f"rs_dev_w1_{suffix}_{os.getpid()}"
    base = ADMIN_DSN.rpartition("/")[0]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield f"{base}/{name}"
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_partial_v1_schema_is_refused_not_adopted(w1_db):
    with _scratch_database("partial") as dsn:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE SCHEMA runtime")
            conn.execute("CREATE TABLE runtime.fixture_state (id smallint PRIMARY KEY, generation bigint NOT NULL)")
        with pytest.raises(RuntimeError, match="missing: .*table runtime.task_grants") as exc:
            db.apply_migrations(dsn)
        assert "trigger recovery.snapshots.snapshots_immutable" in str(exc.value)
        with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
            assert conn.execute("SELECT filename FROM runtime.schema_migrations").fetchall() == []


def test_complete_v1_schema_is_adopted_and_later_migrations_apply(w1_db):
    later = [p.name for p in sorted(db.MIGRATIONS_DIR.glob("*.sql")) if p.name != "001_schema.sql"]
    with _scratch_database("adopt") as dsn:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute((db.MIGRATIONS_DIR / "001_schema.sql").read_text(encoding="utf-8"))
        assert db.apply_migrations(dsn) == later
        with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
            adopted = conn.execute("SELECT filename FROM runtime.schema_migrations WHERE adopted").fetchall()
        assert [r["filename"] for r in adopted] == ["001_schema.sql"]


def test_migration_006_is_applied_exactly_once_to_a_database_at_005(w1_db, tmp_path, monkeypatch):
    real_dir = db.MIGRATIONS_DIR
    upto_005 = tmp_path / "migrations"
    upto_005.mkdir()
    for p in sorted(real_dir.glob("*.sql")):
        if not p.name.startswith("006_"):
            shutil.copy(p, upto_005 / p.name)
    with _scratch_database("upgrade") as dsn:
        monkeypatch.setattr(db, "MIGRATIONS_DIR", upto_005)
        first = db.apply_migrations(dsn)
        assert first[-1] == "005_import_source_metadata.sql" and "006_evidence_append_only.sql" not in first
        monkeypatch.setattr(db, "MIGRATIONS_DIR", real_dir)
        assert db.apply_migrations(dsn) == ["006_evidence_append_only.sql"]
        assert db.apply_migrations(dsn) == []
