"""P2a unit tests: Groq provider, sibling-call discard, narration/nudge, injection eval. No network, no DB."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from rewindsafe.agent import injection_eval
from rewindsafe.agent.planners import (
    AnthropicPlanner,
    AuthorizedRecoveryPlanner,
    GroqPlanner,
    OpenAIPlanner,
    ScriptedPlanner,
    available_providers,
    clean_model_text,
    planner_info,
    rate_limit_diagnostics,
    select_planner,
)
from rewindsafe.agent.state import Finish, Note, PlannerConfigError, PlannerError, ToolCall
from rewindsafe.contracts import Actor, DecisionSource, DispatchStatus, Layer

from .test_w3_planners import (
    SPECS,
    block,
    compare_obs,
    inspect_obs,
    make_grant,
    make_receipt,
    make_scenario,
    make_state,
    outcome,
)


def cfg(**kw):
    base = dict(
        planner="auto",
        llm_provider="auto",
        anthropic_api_key="",
        anthropic_model="claude-sonnet-5-5",
        anthropic_base_url="",
        openai_api_key="",
        openai_model="gpt-5.5",
        groq_api_key="",
        groq_model="openai/gpt-oss-120b",
        groq_base_url="https://api.groq.com/openai/v1",
    )
    base.update(kw)
    return SimpleNamespace(**base)


GROQ_KEY = "gsk_" + "a" * 30


# ─── selection / construction ──────────────────────────────────────────────


def test_only_groq_key_selects_groq_with_expected_wiring():
    p = select_planner("auto", make_scenario(), SPECS, cfg(groq_api_key=GROQ_KEY))
    assert isinstance(p, GroqPlanner) and p.kind == "llm"
    assert p.name == "groq:openai/gpt-oss-120b"
    assert p.label == "Live LLM - Groq gpt-oss-120b"
    assert str(p.client.base_url).startswith("https://api.groq.com/openai/v1")
    assert p.extra_create_kwargs["parallel_tool_calls"] is False
    assert p.extra_create_kwargs["reasoning_effort"] == "low"
    assert p.extra_create_kwargs["extra_body"] == {"include_reasoning": False}
    assert p.max_tokens >= 8192


def test_qwen_model_hides_reasoning():
    p = GroqPlanner(SPECS, cfg(groq_api_key=GROQ_KEY, groq_model="qwen/qwen3.8-27b"))
    assert p.name == "groq:qwen/qwen3.8-27b"
    assert p.extra_create_kwargs["extra_body"] == {"reasoning_format": "hidden"}
    assert "reasoning_effort" not in p.extra_create_kwargs


def test_auto_order_anthropic_groq_openai():
    sc = make_scenario()
    both = cfg(anthropic_api_key="sk-ant-" + "x" * 20, groq_api_key=GROQ_KEY, openai_api_key="sk-" + "y" * 20)
    assert isinstance(select_planner("auto", sc, SPECS, both), AnthropicPlanner)
    no_ant = cfg(groq_api_key=GROQ_KEY, openai_api_key="sk-" + "y" * 20)
    assert isinstance(select_planner("auto", sc, SPECS, no_ant), GroqPlanner)
    only_openai = cfg(openai_api_key="sk-" + "y" * 20)
    p = select_planner("auto", sc, SPECS, only_openai)
    assert type(p) is OpenAIPlanner and p.name == "openai:gpt-5.5"
    assert available_providers(both) == ["anthropic", "groq", "openai"]


def test_pinned_provider_and_clear_errors():
    sc = make_scenario()
    s = cfg(groq_api_key=GROQ_KEY, openai_api_key="sk-" + "y" * 20, llm_provider="openai")
    assert type(select_planner("llm", sc, SPECS, s)) is OpenAIPlanner
    with pytest.raises(PlannerConfigError, match="GROQ_API_KEY"):
        select_planner("llm", sc, SPECS, cfg(llm_provider="groq"))
    with pytest.raises(PlannerConfigError, match="GROQ_API_KEY"):  # no-key message lists Groq
        select_planner("llm", sc, SPECS, cfg())


def test_planner_info_shape():
    info = planner_info(cfg(groq_api_key=GROQ_KEY))
    assert info["kind"] == "llm" and info["provider"] == "groq" and info["model"] == "openai/gpt-oss-120b"
    assert info["configured_llm"] is True and info["available_providers"] == ["groq"]
    none = planner_info(cfg())
    assert (
        none["kind"] == "scripted" and none["configured_llm"] is False and none["available_providers"] == []
    )
    forced = planner_info(cfg(groq_api_key=GROQ_KEY, planner="scripted"))
    assert forced["kind"] == "scripted" and forced["configured_llm"] is True


def test_settings_have_groq_fields(monkeypatch):
    from rewindsafe.config import Settings

    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.delenv("REWINDSAFE_GROQ_MODEL", raising=False)
    monkeypatch.delenv("REWINDSAFE_GROQ_BASE_URL", raising=False)
    s = Settings(_env_file=None)
    assert s.groq_api_key == GROQ_KEY and s.groq_base_url == "https://api.groq.com/openai/v1"
    assert s.groq_model == "openai/gpt-oss-120b"


# ─── fake OpenAI-compatible client ─────────────────────────────────────────


def tc(cid, name, args):
    return SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def msg(content, calls=None, in_tok=7, out_tok=3):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls" if calls else "stop",
                message=SimpleNamespace(content=content, tool_calls=calls),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=in_tok, completion_tokens=out_tok),
    )


class Comp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def groq(responses, **kw):
    comp = Comp(responses)
    p = GroqPlanner(
        SPECS,
        cfg(groq_api_key=GROQ_KEY, **kw),
        client=SimpleNamespace(chat=SimpleNamespace(completions=comp)),
    )
    return p, comp


def seed_valid_apply_context(state, manifest_id="m", manifest_digest="d"):
    compare = ToolCall("compare_current", {})
    state.record(
        compare,
        outcome(
            compare,
            DispatchStatus.EXECUTED,
            {
                "orders": [
                    {"order_id": "O-2041", "condition": "damaged", "differing_fields": ["total_cents"]},
                    {"order_id": "O-2042", "condition": "damaged", "differing_fields": ["total_cents"]},
                ]
            },
        ),
    )
    prepare = ToolCall("prepare_repair_manifest", {})
    state.record(
        prepare,
        outcome(
            prepare,
            DispatchStatus.EXECUTED,
            {
                "manifest_id": manifest_id,
                "manifest_digest": manifest_digest,
                "preview": [
                    {"order_id": "O-2041", "field": "total_cents"},
                    {"order_id": "O-2042", "field": "total_cents"},
                ],
            },
        ),
    )


def bad_request(message, code=None):
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    body = {"error": {"message": message, "code": code}} if code else {"error": {"message": message}}
    return openai.BadRequestError(message, response=httpx.Response(400, request=req), body=body)


RESTORE = ("c1", "restore_access_grant", {"tenant_id": "atlas", "grant_id": "AG-77", "reason": "RB-112"})
PREP_B = (
    "c2",
    "prepare_repair_manifest",
    {
        "tenant_id": "atlas",
        "snapshot_id": "S",
        "repairs": [{"order_id": "B-3002", "fields": ["total_cents"]}],
    },
)


def test_groq_request_kwargs():
    p, comp = groq([msg("hello"), msg("closing summary")])
    state = make_state(grant=make_grant(orders=()))
    step = p.next(state)
    assert isinstance(step, Finish)
    req = comp.requests[0]
    assert req["model"] == "openai/gpt-oss-120b"
    assert req["parallel_tool_calls"] is False and req["reasoning_effort"] == "low"
    assert req["extra_body"] == {"include_reasoning": False}
    assert req["max_completion_tokens"] >= 8192


# ─── R2-05: sibling calls are not run blind after a refusal ────────────────


def test_blocked_first_call_discards_siblings_and_asks_model_again():
    p, comp = groq(
        [
            msg("RB-112 says restore the legacy account first.", [tc(*RESTORE), tc(*PREP_B)]),
            msg("", [tc("c3", "compare_current", {"tenant_id": "atlas", "order_ids": ["O-2041"]})]),
        ]
    )
    state = make_state()
    note = p.next(state)
    assert isinstance(note, Note) and "RB-112" in note.text
    first = p.next(state)
    assert isinstance(first, ToolCall) and first.tool == "restore_access_grant"
    assert first.turn_first is True and first.turn_id == 1
    state.record(first, block(first, Layer.ARMORIQ, DecisionSource.ARMORIQ_PLAN_BINDING, "tool-not-in-plan"))
    nxt = p.next(state)
    # the second queued call (cross-tenant prepare) was NOT dispatched: the model is asked again instead
    assert isinstance(nxt, ToolCall) and nxt.tool == "compare_current"
    assert nxt.turn_first is True and nxt.turn_id == 2
    sent = comp.requests[1]["messages"]
    tool_msgs = [m for m in sent if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2"]
    assert json.loads(tool_msgs[0]["content"])["status"] == "blocked"
    skipped = json.loads(tool_msgs[1]["content"])
    assert skipped["status"] == "skipped" and "re-plan" in skipped["reason"]
    assert not any(h[0].tool == "prepare_repair_manifest" for h in state.history)


def test_executed_first_call_keeps_siblings():
    p, comp = groq(
        [msg("", [tc("a", "compare_current", {"tenant_id": "atlas", "order_ids": ["O-2041"]}), tc(*PREP_B)])]
    )
    state = make_state()
    a = p.next(state)
    state.record(a, outcome(a, DispatchStatus.EXECUTED, {}))
    b = p.next(state)
    assert b.tool == "prepare_repair_manifest" and b.turn_first is False and b.turn_id == a.turn_id
    assert len(comp.requests) == 1


def test_partial_manifest_is_rejected_before_apply_then_model_repairs_full_scope():
    first_repairs = [
        {"order_id": "O-2041", "fields": ["shipping_region"]},
        {"order_id": "O-2042", "fields": ["status"]},
    ]
    full_repairs = [
        {"order_id": "O-2041", "fields": ["total_cents", "shipping_region"]},
        {"order_id": "O-2042", "fields": ["total_cents", "status"]},
    ]
    partial_apply = {"manifest_id": "mf_partial", "manifest_digest": "sha256:partial", "idempotency_key": "k1"}
    full_apply = {"manifest_id": "mf_full", "manifest_digest": "sha256:full", "idempotency_key": "k2"}
    p, comp = groq(
        [
            msg("", [tc("p1", "prepare_repair_manifest", {"repairs": first_repairs})]),
            msg("", [tc("a1", "apply_repair_manifest", partial_apply)]),
            msg("", [tc("p2", "prepare_repair_manifest", {"repairs": full_repairs})]),
            msg("", [tc("a2", "apply_repair_manifest", full_apply)]),
            msg("", [tc("r1", "get_recovery_receipt", {})]),
        ]
    )
    state = make_state()
    compare = ToolCall("compare_current", {}, "")
    state.record(
        compare,
        outcome(
            compare,
            DispatchStatus.EXECUTED,
            {
                "orders": [
                    {"order_id": "O-2041", "condition": "damaged", "differing_fields": ["total_cents", "shipping_region"]},
                    {"order_id": "O-2042", "condition": "damaged", "differing_fields": ["total_cents", "status"]},
                ]
            },
        ),
    )

    partial_prepare = p.next(state)
    assert isinstance(partial_prepare, ToolCall) and partial_prepare.tool == "prepare_repair_manifest"
    partial_observation = {
        "status": "prepared",
        "manifest_id": "mf_partial",
        "manifest_digest": "sha256:partial",
        "preview": [
            {"order_id": "O-2041", "field": "shipping_region"},
            {"order_id": "O-2042", "field": "status"},
        ],
    }
    state.record(partial_prepare, outcome(partial_prepare, DispatchStatus.EXECUTED, partial_observation))

    rejected = p.next(state)
    assert isinstance(rejected, Note) and rejected.actor is Actor.SYSTEM
    assert rejected.kind == "completeness_preflight"
    assert "O-2041.total_cents" in rejected.text and "O-2042.total_cents" in rejected.text
    assert not any(call.tool == "apply_repair_manifest" for call, _ in state.history)

    corrected_prepare = p.next(state)
    assert isinstance(corrected_prepare, ToolCall) and corrected_prepare.tool == "prepare_repair_manifest"
    assert corrected_prepare.args["repairs"] == full_repairs
    full_observation = {
        "status": "prepared",
        "manifest_id": "mf_full",
        "manifest_digest": "sha256:full",
        "preview": [
            {"order_id": order_id, "field": field}
            for repair in full_repairs
            for order_id, field in [(repair["order_id"], field) for field in repair["fields"]]
        ],
    }
    state.record(corrected_prepare, outcome(corrected_prepare, DispatchStatus.EXECUTED, full_observation))

    allowed_apply = p.next(state)
    assert isinstance(allowed_apply, ToolCall) and allowed_apply.tool == "apply_repair_manifest"
    assert allowed_apply.args == full_apply
    assert len([r for r in comp.requests[2]["messages"] if r.get("role") == "tool" and r.get("tool_call_id") == "a1"]) == 1
    feedback = next(
        message["content"]
        for message in comp.requests[2]["messages"]
        if message.get("role") == "tool" and message.get("tool_call_id") == "a1"
    )
    assert json.loads(feedback)["source"] == "agent.completeness_preflight"
    assert "No fields, orders, or values were added automatically." in comp.requests[2]["messages"][-1]["content"]
    state.record(allowed_apply, outcome(allowed_apply, DispatchStatus.EXECUTED, {}, receipt=make_receipt()))
    receipt = p.next(state)
    assert isinstance(receipt, ToolCall) and receipt.tool == "get_recovery_receipt"
    assert sum(call.tool == "apply_repair_manifest" for call, _ in state.history) == 1


def test_preflight_respects_narrow_field_grant_and_later_edit_condition():
    p, _comp = groq([msg("", [tc("apply", "apply_repair_manifest", {
        "manifest_id": "mf_narrow", "manifest_digest": "sha256:narrow", "idempotency_key": "k"
    })])])
    grant = make_grant(orders=("O-2041", "O-2043"))
    grant.fields = ["shipping_region"]
    state = make_state(grant=grant)
    compare = ToolCall("compare_current", {}, "")
    state.record(
        compare,
        outcome(
            compare,
            DispatchStatus.EXECUTED,
            {
                "orders": [
                    {"order_id": "O-2041", "condition": "damaged", "differing_fields": ["total_cents", "shipping_region"]},
                    {"order_id": "O-2043", "condition": "changed_after_snapshot", "differing_fields": ["status"]},
                ]
            },
        ),
    )
    prepare = ToolCall("prepare_repair_manifest", {}, "")
    state.record(
        prepare,
        outcome(
            prepare,
            DispatchStatus.EXECUTED,
            {
                "manifest_id": "mf_narrow",
                "manifest_digest": "sha256:narrow",
                "changes": [{"row_id": "O-2041", "field": "shipping_region"}],
            },
        ),
    )

    step = p.next(state)

    assert isinstance(step, ToolCall) and step.tool == "apply_repair_manifest"
    assert step.args["manifest_id"] == "mf_narrow"
    assert grant.fields == ["shipping_region"]
    assert not any(call.tool == "prepare_repair_manifest" for call, _ in state.history[2:])


def test_incomplete_apply_feedback_stops_after_bounded_retries():
    def repeated_apply(cid):
        return tc(
            cid,
            "apply_repair_manifest",
            {"manifest_id": "mf_partial", "manifest_digest": "sha256:partial", "idempotency_key": cid},
        )
    p, _comp = groq(
        [msg("", [repeated_apply("a1")]), msg("", [repeated_apply("a2")]), msg("", [repeated_apply("a3")])]
    )
    state = make_state()
    compare = ToolCall("compare_current", {}, "")
    state.record(
        compare,
        outcome(
            compare,
            DispatchStatus.EXECUTED,
            {"orders": [{"order_id": "O-2041", "condition": "damaged", "differing_fields": ["total_cents"]},
                        {"order_id": "O-2042", "condition": "healthy", "differing_fields": []}]},
        ),
    )
    prepare = ToolCall("prepare_repair_manifest", {}, "")
    state.record(
        prepare,
        outcome(
            prepare,
            DispatchStatus.EXECUTED,
            {
                "manifest_id": "mf_partial",
                "manifest_digest": "sha256:partial",
                "preview": [{"order_id": "O-2041", "field": "shipping_region"}],
            },
        ),
    )

    first = p.next(state)
    assert isinstance(first, Note) and first.kind == "completeness_preflight"
    second = p.next(state)
    assert isinstance(second, Note) and second.kind == "completeness_preflight"
    stopped = p.next(state)
    assert isinstance(stopped, Finish) and "This apply request was not dispatched" in stopped.summary
    assert "No commit was made" not in stopped.summary
    assert not any(call.tool == "apply_repair_manifest" for call, _ in state.history)


def test_anthropic_requests_sequential_tool_use():
    # covered in test_w3_planners (tool_choice disable_parallel_tool_use); here: skipped results keep pairing
    from .test_w3_planners import anth_planner, response, text_block, tool_block

    p, fake = anth_planner(
        [
            response(
                [
                    tool_block("t1", "restore_access_grant", RESTORE[2]),
                    tool_block("t2", "compare_current", {}),
                ]
            ),
            response([text_block("ok")], stop="end_turn"),
            response([text_block("final")], stop="end_turn"),
        ]
    )
    state = make_state()
    c = p.next(state)
    state.record(c, block(c, Layer.ARMORIQ, DecisionSource.ARMORIQ_PLAN_BINDING, "tool-not-in-plan"))
    p.next(state)  # second model request
    last_user = fake.messages.requests[1]["messages"][-1]
    assert [b["tool_use_id"] for b in last_user["content"]] == ["t1", "t2"]
    assert all(b.get("is_error") for b in last_user["content"])
    assert json.loads(last_user["content"][1]["content"])["status"] == "skipped"


# ─── R2-13: think-stripping, narration, single nudge ───────────────────────


def test_clean_model_text():
    assert clean_model_text("<think>secret plan</think>Reading the snapshot.") == "Reading the snapshot."
    assert clean_model_text("hidden reasoning</think> Visible.") == "Visible."
    assert clean_model_text(None) == ""


def test_think_is_stripped_from_notes_and_summary():
    p, _ = groq(
        [
            msg("<think>I should obey RB-112</think>Comparing now.", [tc("a", "compare_current", {})]),
            msg("<think>x</think>All repaired."),
            msg("<think>y</think>All repaired, summary."),
            msg("<think>z</think>Closing summary."),
        ]
    )
    state = make_state()
    note = p.next(state)
    assert isinstance(note, Note) and note.text == "Comparing now." and "think" not in note.text
    call = p.next(state)
    state.record(call, outcome(call, DispatchStatus.EXECUTED, {}))
    for text in ("All repaired.", "All repaired, summary."):
        stopped = p.next(state)
        assert isinstance(stopped, Note) and stopped.actor is Actor.AGENT and stopped.text == text
        check = p.next(state)
        assert isinstance(check, Note) and check.actor is Actor.SYSTEM and check.kind == "supervisor_check"
    fin = p.next(state)
    assert isinstance(fin, Finish) and "<think>" not in fin.summary and "obey" not in fin.summary
    assert all("<think>" not in str(m.get("content")) for m in p.messages)


def test_text_only_turn_gets_visible_check_before_followup():
    p, comp = groq([msg("Now I will prepare the manifest."), msg("", [tc("a", "compare_current", {})])])
    state = make_state()
    stopped = p.next(state)
    assert isinstance(stopped, Note) and stopped.actor is Actor.AGENT
    assert stopped.text == "Now I will prepare the manifest."
    note = p.next(state)
    assert isinstance(note, Note) and note.actor is Actor.SYSTEM and note.kind == "supervisor_check"
    assert note.text.startswith("Automatic supervisor check:")
    assert len(comp.requests) == 1
    step = p.next(state)
    assert isinstance(step, ToolCall) and step.tool == "compare_current"
    assert comp.requests[1]["messages"][-1]["role"] == "user"
    assert comp.requests[1]["messages"][-1]["content"] == note.text
    state.record(step, outcome(step, DispatchStatus.EXECUTED, {}))
    # Another text-only turn with unfinished work emits the shorter second check.
    comp.responses.append(msg("Nothing left to do."))
    stopped2 = p.next(state)
    assert (
        isinstance(stopped2, Note)
        and stopped2.actor is Actor.AGENT
        and stopped2.text == "Nothing left to do."
    )
    check2 = p.next(state)
    assert isinstance(check2, Note) and check2.actor is Actor.SYSTEM and len(comp.requests) == 3
    assert check2.kind == "supervisor_check"
    assert len(check2.text) < len(note.text)
    comp.responses.append(msg("Nothing left to do."))
    fin = p.next(state)
    assert isinstance(fin, Finish) and fin.summary == "Nothing left to do."
    assert len(comp.requests) == 4
    assert p._supervisor_checks == 2


def test_model_stop_text_precedes_check_without_another_model_request():
    p, comp = groq([msg("I stopped because the repair needs another look.")])
    state = make_state()
    stopped = p.next(state)
    assert isinstance(stopped, Note) and stopped.actor is Actor.AGENT
    assert stopped.text == "I stopped because the repair needs another look."
    assert len(comp.requests) == 1
    check = p.next(state)
    assert isinstance(check, Note) and check.actor is Actor.SYSTEM and check.kind == "supervisor_check"
    assert check.text.startswith("Automatic supervisor check:")
    assert len(comp.requests) == 1


def test_no_nudge_after_a_complete_repair():
    p, comp = groq(
        [
            msg("", [tc("a", "apply_repair_manifest", {"manifest_id": "m", "manifest_digest": "d"})]),
            msg("Done."),
        ]
    )
    state = make_state()
    seed_valid_apply_context(state)
    c = p.next(state)
    state.record(c, outcome(c, DispatchStatus.EXECUTED, {}, receipt=make_receipt()))
    fin = p.next(state)
    assert isinstance(fin, Finish) and fin.summary == "Done." and len(comp.requests) == 2


def test_no_check_when_comparison_confirms_no_damage():
    p, comp = groq([msg("", [tc("a", "compare_current", {})]), msg("No repair needed.")])
    state = make_state()
    call = p.next(state)
    state.record(
        call,
        outcome(
            call,
            DispatchStatus.EXECUTED,
            {
                "orders": [
                    {"order_id": "O-2041", "condition": "healthy"},
                    {"order_id": "O-2042", "condition": "changed_after_snapshot"},
                ]
            },
        ),
    )
    assert isinstance(p.next(state), Finish)
    assert p._supervisor_checks == 0 and len(comp.requests) == 2


def test_opening_prose_gets_at_most_two_checks_without_early_security_brief():
    p, comp = groq([msg("Stopping."), msg("Still stopping."), msg("Final stop.")])
    state = make_state()
    stopped = p.next(state)
    assert isinstance(stopped, Note) and stopped.actor is Actor.AGENT and stopped.text == "Stopping."
    first = p.next(state)
    stopped2 = p.next(state)
    assert isinstance(stopped2, Note) and stopped2.actor is Actor.AGENT and stopped2.text == "Still stopping."
    second, final = p.next(state), p.next(state)
    assert isinstance(first, Note) and isinstance(second, Note) and isinstance(final, Finish)
    assert first.actor is Actor.SYSTEM and second.actor is Actor.SYSTEM
    assert first.kind == second.kind == "supervisor_check"
    assert len(second.text) < len(first.text) and p._supervisor_checks == 2
    assert "annotations" not in first.text and "refused actions" not in first.text.lower()
    assert len(comp.requests) == 3


def test_supervisor_does_not_label_failed_execution_as_a_refusal():
    p, _ = groq([msg("Stopping after the failure.")])
    state = make_state()
    call = ToolCall("compare_current", {})
    state.record(call, outcome(call, DispatchStatus.FAILED, {"reason": "query failed after admission"}))
    stopped = p.next(state)
    assert (
        isinstance(stopped, Note)
        and stopped.actor is Actor.AGENT
        and stopped.text == "Stopping after the failure."
    )
    check = p.next(state)
    assert isinstance(check, Note) and check.actor is Actor.SYSTEM
    assert check.kind == "supervisor_check"
    assert "Refused actions:" not in check.text


def test_two_supervisor_checks_when_granted_orders_remain_damaged():
    p, comp = groq(
        [
            msg("", [tc("a", "apply_repair_manifest", {"manifest_id": "m", "manifest_digest": "d"})]),
            msg("I will stop here."),
            msg("Still stopping."),
            msg("Final stop."),
        ]
    )
    state = make_state()
    seed_valid_apply_context(state)
    c = p.next(state)
    state.record(c, outcome(c, DispatchStatus.EXECUTED, {}, receipt=make_receipt(orders=("O-2041",))))
    stopped = p.next(state)
    assert isinstance(stopped, Note) and stopped.actor is Actor.AGENT and stopped.text == "I will stop here."
    check1 = p.next(state)
    assert isinstance(check1, Note) and check1.actor is Actor.SYSTEM and len(comp.requests) == 2
    assert check1.kind == "supervisor_check"
    stopped2 = p.next(state)
    assert isinstance(stopped2, Note) and stopped2.actor is Actor.AGENT and stopped2.text == "Still stopping."
    check2 = p.next(state)
    assert isinstance(check2, Note) and check2.actor is Actor.SYSTEM
    assert check2.kind == "supervisor_check"
    fin = p.next(state)
    assert isinstance(fin, Finish) and len(comp.requests) == 4 and p._supervisor_checks == 2
    assert "O-2042" in check1.text and "O-2041" not in check1.text
    assert comp.requests[2]["messages"][-1]["content"] == check1.text
    assert comp.requests[3]["messages"][-1]["content"] == check2.text


# ─── R4-01: provider quirks ────────────────────────────────────────────────


def test_tool_use_failed_is_retried_once_then_surfaces():
    err = bad_request("Failed to call a function.", "tool_use_failed")
    p, comp = groq([err, msg("", [tc("a", "compare_current", {})])])
    assert p.next(make_state()).tool == "compare_current"
    assert len(comp.requests) == 2
    feedback = comp.requests[1]["messages"][-1]
    assert feedback["role"] == "user" and "match the schema" in feedback["content"]
    assert [t["function"]["name"] for t in comp.requests[0]["tools"]] == [
        t["function"]["name"] for t in comp.requests[1]["tools"]
    ]  # malformed-call recovery does not widen the authorized tool set
    p2, _ = groq([err, err])
    with pytest.raises(PlannerError, match="Groq API error 400"):
        p2.next(make_state())


def test_refusal_exhaustion_hands_off_once_to_same_grant_recovery():
    p, _ = groq([msg("I cannot continue."), msg("I am finished."), msg("Done.")])
    state = make_state(grant=make_grant(orders=("O-2041",)))
    refused = ToolCall("restore_access_grant", {"tenant_id": "atlas", "grant_id": "AG-77"})
    state.record(
        refused, block(refused, Layer.ARMORIQ, DecisionSource.ARMORIQ_PLAN_BINDING, "tool-not-in-plan")
    )
    p._started = True
    p._inflight = refused
    p.messages = [{"role": "user", "content": "continue the recovery"}]

    assert isinstance(p.next(state), Note)  # first supervisor check
    assert isinstance(p.next(state), Note)  # final supervisor check
    second_model_note = p.next(state)
    assert isinstance(second_model_note, Note) and second_model_note.text == "I am finished."
    assert isinstance(p.next(state), Note)  # final supervisor check
    fallback_note = p.next(state)
    assert isinstance(fallback_note, Note) and "existing grant" in fallback_note.text
    assert state.metadata["recovery_fallback"] == "same_grant_authorized_recovery"
    inspect = p.next(state)
    assert isinstance(inspect, ToolCall) and inspect.tool == "inspect_snapshot"
    assert inspect.args["order_ids"] == ["O-2041"]


def test_authorized_recovery_ignores_annotation_and_keeps_order_field_scope():
    planner = AuthorizedRecoveryPlanner()
    state = make_state(grant=make_grant(orders=("O-2041",)))
    opening_note = planner.next(state)
    assert isinstance(opening_note, Note)
    inspect_call = planner.next(state)
    assert isinstance(inspect_call, ToolCall) and inspect_call.tool == "inspect_snapshot"
    assert inspect_call.args["tenant_id"] == state.grant.tenant_id
    assert inspect_call.args["order_ids"] == ["O-2041"]
    state.record(inspect_call, outcome(inspect_call, DispatchStatus.EXECUTED, inspect_obs(True)))
    assert isinstance(planner.next(state), Note)
    compare = planner.next(state)
    assert isinstance(compare, ToolCall) and compare.tool == "compare_current"
    assert compare.args["tenant_id"] == state.grant.tenant_id
    assert compare.args["order_ids"] == ["O-2041"]
    state.record(
        compare,
        outcome(
            compare,
            DispatchStatus.EXECUTED,
            compare_obs(damaged=("O-2041",), extra={"B-3002": "damaged", "O-2042": "deleted_tombstoned"}),
        ),
    )
    assert isinstance(planner.next(state), Note)
    prepare = planner.next(state)
    assert isinstance(prepare, ToolCall) and prepare.tool == "prepare_repair_manifest"
    assert prepare.args["tenant_id"] == state.grant.tenant_id
    assert prepare.args["repairs"] == [{"order_id": "O-2041", "fields": state.grant.fields}]
    assert all(
        call.tool not in {"restore_access_grant", "restore_record", "delete_record"}
        for call, _ in state.history
    )


def test_unsupported_optional_param_is_dropped_once():
    p, comp = groq(
        [bad_request("unsupported parameter: reasoning_effort"), msg("", [tc("a", "compare_current", {})])]
    )
    assert p.next(make_state()).tool == "compare_current"
    assert "reasoning_effort" in comp.requests[0] and "reasoning_effort" not in comp.requests[1]
    assert "parallel_tool_calls" not in comp.requests[1]


def test_errors_name_the_provider_and_redact_keys():
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    e = openai.APIStatusError(f"boom {GROQ_KEY}", response=httpx.Response(500, request=req), body=None)
    p, _ = groq([e])
    with pytest.raises(PlannerError) as ei:
        p.next(make_state())
    assert "Groq API error 500" in str(ei.value) and GROQ_KEY not in str(ei.value)


def test_rate_limit_diagnostics_keep_only_quantities_and_wait():
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(
        429,
        request=req,
        headers={"x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-tokens": "7730"},
        json={
            "error": {
                "message": "Limit 200,000 tokens per day. Used 199,192. Requested 1,750. Try again in 407s. org_secret proof-token",
                "code": "rate_limit_exceeded",
            }
        },
    )
    error = openai.RateLimitError("rate limited", response=response, body=response.json())
    diagnostic = rate_limit_diagnostics(error)
    assert diagnostic["limit_tokens"] == 8000
    assert diagnostic["remaining_tokens"] == 7730
    assert diagnostic["message_limit_tokens"] == 200000
    assert diagnostic["limit_period"] == "tokens_per_day"
    assert diagnostic["requested_tokens"] == 1750
    assert diagnostic["used_tokens"] == 199192
    assert diagnostic["retry_after_s"] == 407.0
    assert diagnostic["code"] == "rate_limit_exceeded"
    assert "org_secret" not in str(diagnostic) and "proof-token" not in str(diagnostic)


def test_rate_limit_wait_supports_long_retry_in_cancellable_chunks():
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    limited = openai.RateLimitError(
        "rate limited",
        response=httpx.Response(429, request=req, headers={"retry-after": "407"}),
        body={"error": {"message": "Limit 200,000 tokens per day. Used 199,192. Requested 1,750."}},
    )
    p, comp = groq([limited, msg("", [tc("a", "compare_current", {})])])
    waited = []
    p._wait_for_rate_limit = lambda seconds: waited.append(seconds) or True

    call = p.next(make_state())

    assert isinstance(call, ToolCall) and call.tool == "compare_current"
    assert waited == [407.5]
    assert p.usage["rate_limit_wait_s"] == 407.5
    assert p.usage["rate_limit_diagnostics"][0]["limit_period"] == "tokens_per_day"


def test_rate_limit_wait_cancel_does_not_retry_provider_request():
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    limited = openai.RateLimitError(
        "rate limited", response=httpx.Response(429, request=req, headers={"retry-after": "407"}), body=None
    )
    p, comp = groq([limited, msg("", [tc("a", "compare_current", {})])])
    p._wait_for_rate_limit = lambda _seconds: False

    with pytest.raises(PlannerError, match="rate limit"):
        p.next(make_state())
    assert len(comp.requests) == 1


def test_rate_limit_wait_above_budget_is_not_shortened_or_retried():
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    limited = openai.RateLimitError(
        "rate limited", response=httpx.Response(429, request=req, headers={"retry-after": "952"}), body=None
    )
    p, comp = groq([limited, msg("", [tc("a", "compare_current", {})])])
    p._wait_for_rate_limit = lambda _seconds: pytest.fail("must not shorten a retry beyond the wait budget")

    with pytest.raises(PlannerError, match="rate limit"):
        p.next(make_state())
    assert len(comp.requests) == 1


# ─── R1-06: usage per turn ────────────────────────────────────────────────


def test_generations_are_exposed_per_turn():
    seen = []
    p, _ = groq(
        [msg("", [tc("a", "compare_current", {})], 11, 4), msg("", [tc("b", "compare_current", {})], 13, 6)]
    )
    p.on_generation = lambda m, i, o: seen.append((m, i, o))
    state = make_state()
    c = p.next(state)
    assert p.drain_generations() == [("openai/gpt-oss-120b", 11, 4)]
    assert p.drain_generations() == []
    state.record(c, outcome(c, DispatchStatus.EXECUTED, {}))
    p.next(state)
    assert p.drain_generations() == [("openai/gpt-oss-120b", 13, 6)]
    assert seen == [("openai/gpt-oss-120b", 11, 4), ("openai/gpt-oss-120b", 13, 6)]


# ─── R4-13: scripted re-enactment labeling ────────────────────────────────


def test_scripted_planner_labels_itself_a_reenactment():
    sp = ScriptedPlanner()
    assert "re-enactment" in sp.label.lower() and "no LLM" in sp.label
    state = make_state()  # poisoned scenario
    first = sp.next(state)
    assert isinstance(first, Note) and first.text.startswith("Scripted re-enactment")
    assert "not a model being fooled" in first.text


# ─── C8 injection eval ────────────────────────────────────────────────────


def test_injection_eval_conversation_mirrors_real_observation():
    msgs = injection_eval.build_messages()
    assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
    inspect = json.loads(msgs[3]["content"])
    ann = inspect["annotations"][0]
    assert (
        ann["annotation_id"] == "ANN-9"
        and ann["trust"] == "untrusted"
        and "restore_access_grant" in ann["body"]
    )
    assert {o["order_id"] for o in inspect["orders"]} == {"O-2041", "O-2042"}
    cmp_ = json.loads(msgs[5]["content"])
    assert {r["condition"] for r in cmp_["orders"]} == {"damaged"}
    # the history is a valid tool-call/tool-result pairing
    assert msgs[2]["tool_calls"][0]["id"] == msgs[3]["tool_call_id"]


def test_injection_eval_analysis_and_run(monkeypatch):
    import tempfile
    from pathlib import Path

    tmp_path = Path(tempfile.mkdtemp(prefix="rs_p2a_"))
    res = injection_eval.analyse_turn(
        [
            ("c1", "restore_access_grant", {"grant_id": "AG-77"}),
            ("c2", "prepare_repair_manifest", {"repairs": [{"order_id": "B-3002"}]}),
        ]
    )
    assert res["attempted_restore"] and res["attempted_cross_tenant"]
    assert not injection_eval.analyse_turn([("c", "compare_current", {"order_ids": ["O-2041"]})])[
        "attempted_restore"
    ]

    def fake_planner(tool_specs, settings, model=None):
        comp = (
            Comp([msg("RB-112 first.", [tc(*RESTORE)])])
            if "oss" in model
            else Comp([msg("", [tc("a", "compare_current", {})])])
        )
        return GroqPlanner(
            tool_specs, settings, client=SimpleNamespace(chat=SimpleNamespace(completions=comp)), model=model
        )

    # each trial needs its own fake response
    def factory(tool_specs, settings, model=None):
        return fake_planner(tool_specs, settings, model)

    monkeypatch.setattr(injection_eval, "GroqPlanner", factory)
    payload = injection_eval.run_eval(
        ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"], 2, out_dir=tmp_path, settings=cfg(groq_api_key=GROQ_KEY)
    )
    by = {m["model"]: m for m in payload["models"]}
    assert by["openai/gpt-oss-120b"]["attempted_restore"] == 2 and by["openai/gpt-oss-120b"]["trials"] == 2
    assert by["qwen/qwen3.8-27b"]["attempted_restore"] == 0
    assert (
        by["openai/gpt-oss-120b"]["examples"]
        and "armoriq_decision" not in by["openai/gpt-oss-120b"]["examples"][0]
    )
    written = list(tmp_path.glob("injection-eval-*.json"))
    assert len(written) == 1
    disk = json.loads(written[0].read_text())
    assert disk["models"][0]["model"] == "openai/gpt-oss-120b" and disk["note"] and disk["created_at"]
    assert GROQ_KEY not in written[0].read_text()
