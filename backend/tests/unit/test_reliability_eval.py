"""Pure reliability-evaluation helpers; live runs require explicit CLI invocation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from rewindsafe.agent import reliability_eval
from rewindsafe.agent.reliability_eval import (
    _database_url_with_name,
    _failure_cause,
    _summarize,
    wilson_interval,
)


def test_database_target_replaces_only_database_name():
    dsn = "postgresql://user:pass@db.example:5432/preview?sslmode=require"
    isolated = _database_url_with_name(dsn, "rs_reliability_test")
    assert isolated == "postgresql://user:pass@db.example:5432/rs_reliability_test?sslmode=require"
    assert "/preview" not in isolated


def test_wilson_interval_handles_empty_and_extreme_samples():
    assert wilson_interval(0, 0) is None
    assert wilson_interval(0, 20) == [0.0, 0.16112515805281938]
    assert wilson_interval(20, 20) == [0.8388748419471806, 1.0]


def test_summary_reports_completion_and_attack_intervals_per_briefing_model():
    payload = {
        "trials": [
            {
                "briefing": "task_only",
                "model": "groq/test",
                "completed": True,
                "attempted_restore": 1,
                "forbidden_effects": 0,
                "evidence_complete": True,
                "failed": False,
            },
            {
                "briefing": "task_only",
                "model": "groq/test",
                "completed": False,
                "attempted_restore": 0,
                "forbidden_effects": 0,
                "evidence_complete": True,
                "failed": True,
                "failure_cause": "provider_connection",
            },
        ]
    }
    _summarize(payload)
    result = payload["summary"]["task_only|groq/test"]
    assert result["trials"] == 2 and result["completed"] == 1
    assert result["completion_wilson_95"] == wilson_interval(1, 2)
    assert result["restore_attempt_wilson_95"] == wilson_interval(1, 2)
    assert result["forbidden_effects"] == 0 and result["failures"] == 1
    assert result["failure_breakdown"] == {"provider_connection": 1}


def test_unknown_safety_evidence_is_not_counted_as_zero():
    payload = {
        "trials": [
            {
                "briefing": "task_only",
                "model": "groq/test",
                "completed": False,
                "attempted_restore": None,
                "forbidden_effects": None,
                "evidence_complete": False,
                "failed": True,
                "failure_cause": "database_or_fixture_error",
                "raw_llm_completed": None,
            }
        ]
    }
    _summarize(payload)
    result = payload["summary"]["task_only|groq/test"]
    assert result["forbidden_effects"] is None
    assert result["known_forbidden_effects"] == 0 and result["unknown_safety_trials"] == 1
    assert result["restore_attempt_trials"] is None and result["unknown_attempt_trials"] == 1
    assert result["raw_llm_completion_rate"] is None and result["unknown_raw_llm_trials"] == 1


def test_failure_cause_taxonomy():
    assert _failure_cause(failure="Groq rate limit reached", status="failed") == "provider_rate_limit"
    assert (
        _failure_cause(failure=None, status="succeeded", evidence_complete=False)
        == "safety_evidence_unavailable"
    )
    assert _failure_cause(failure="", status="succeeded", forbidden_effects=1) == "forbidden_effect"
    assert (
        _failure_cause(
            failure="ArmorIQ refused a poison action, then only part of the authorized repair was committed.",
            status="partially_succeeded",
            evidence_complete=True,
            forbidden_effects=0,
        )
        == "partial_repair"
    )


def test_runner_fingerprint_covers_behavior_sources():
    fingerprint, sources = reliability_eval._runner_fingerprint()
    assert len(fingerprint) == 64
    assert {
        "backend/rewindsafe/agent/planners.py",
        "backend/rewindsafe/agent/loop.py",
        "backend/rewindsafe/runtime/dispatch.py",
        "backend/rewindsafe/workflows/rewindsafe/fixture.py",
    } <= set(sources)


def test_summary_preserves_full_target_for_unstarted_groups():
    payload = {
        "models": ["groq/test"],
        "briefings": ["task_only", "with_rules"],
        "trials_per_group": 20,
        "trials": [
            {"briefing": "task_only", "model": "groq/test", "status": "completed", "completed": True}
        ],
    }
    _summarize(payload)

    assert payload["summary"]["task_only|groq/test"]["trials"] == 1
    assert payload["summary"]["task_only|groq/test"]["target_trials"] == 20
    assert payload["summary"]["task_only|groq/test"]["pending_trials"] == 19
    assert payload["summary"]["task_only|groq/test"]["group_complete"] is False
    assert payload["summary"]["with_rules|groq/test"]["trials"] == 0
    assert payload["summary"]["with_rules|groq/test"]["pending_trials"] == 20
    assert "recorded 1/20 (pending 19)" in reliability_eval.summary_line(payload)


def test_invocation_cap_resumes_same_full_cohort_without_duplicates(tmp_path, monkeypatch):
    class FakeDatabase:
        def __init__(self, _dsn):
            pass

        def __enter__(self):
            return self

        def reset_fixture(self):
            pass

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(
        reliability_eval,
        "get_settings",
        lambda: SimpleNamespace(
            effective_enforcement=lambda: "live",
            armoriq_api_key="test-key",
            groq_api_key="test-key",
            database_url="postgresql://unused",
        ),
    )
    monkeypatch.setattr(reliability_eval, "reload_settings", lambda: None)
    monkeypatch.setattr(reliability_eval, "IsolatedEvaluationDatabase", FakeDatabase)
    calls = []

    def fake_trial(model, briefing, trial, _timeout):
        calls.append((briefing, model, trial))
        return {
            "briefing": briefing,
            "model": model,
            "trial": trial,
            "status": "completed",
            "completed": True,
            "failed": False,
            "attempted_restore": 1,
            "forbidden_effects": 0,
            "evidence_complete": True,
        }

    monkeypatch.setattr(reliability_eval, "_run_trial", fake_trial)
    out = tmp_path / "cohort.json"
    config = {"models": ["groq/test"], "briefings": ["task_only", "with_rules"], "trials": 2}
    partial = reliability_eval.run_eval(
        **config, out_path=out, max_trials_per_invocation=3
    )

    assert partial["requested_trials"] == 4
    assert partial["pending_trials"] == 1
    assert partial["cohort_status"] == "incomplete"
    assert partial["invocation_status"] == "trial_limit_reached"
    assert "finished_at" not in partial
    assert partial["summary"]["task_only|groq/test"]["trials"] == 2
    assert partial["summary"]["with_rules|groq/test"]["trials"] == 1

    complete = reliability_eval.run_eval(
        **config, resume_path=out, max_trials_per_invocation=3
    )

    assert len(calls) == 4
    assert len(complete["trials"]) == 4
    assert len({(r["briefing"], r["model"], r["trial"]) for r in complete["trials"]}) == 4
    assert complete["cohort_status"] == "complete"
    assert complete["invocation_status"] == "complete"
    assert complete["pending_trials"] == 0
    assert complete["invocation_completed_trials"] == 1
    assert "finished_at" in complete


def test_invocation_cap_must_be_positive():
    with pytest.raises(ValueError, match="max-trials-per-invocation"):
        reliability_eval.run_eval(max_trials_per_invocation=0)


def test_rate_limit_stop_records_failure_and_resume_keeps_it(tmp_path, monkeypatch):
    class FakeDatabase:
        def __init__(self, _dsn):
            pass

        def __enter__(self):
            return self

        def reset_fixture(self):
            pass

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(
        reliability_eval,
        "get_settings",
        lambda: SimpleNamespace(
            effective_enforcement=lambda: "live",
            armoriq_api_key="test-key",
            groq_api_key="test-key",
            database_url="postgresql://unused",
        ),
    )
    monkeypatch.setattr(reliability_eval, "reload_settings", lambda: None)
    monkeypatch.setattr(reliability_eval, "IsolatedEvaluationDatabase", FakeDatabase)
    calls = []

    def fake_trial(model, briefing, trial, _timeout):
        calls.append((briefing, model, trial))
        if trial == 1:
            raise RuntimeError("Groq rate limit reached; try again shortly.")
        return {
            "briefing": briefing,
            "model": model,
            "trial": trial,
            "status": "completed",
            "completed": True,
            "failed": False,
            "attempted_restore": 1,
            "forbidden_effects": 0,
            "evidence_complete": True,
        }

    monkeypatch.setattr(reliability_eval, "_run_trial", fake_trial)
    out = tmp_path / "rate-limited-cohort.json"
    config = {"models": ["groq/test"], "briefings": ["task_only"], "trials": 3}
    partial = reliability_eval.run_eval(**config, out_path=out, stop_on_rate_limit=True)

    assert calls == [("task_only", "groq/test", 1)]
    assert partial["invocation_status"] == "provider_rate_limit"
    assert partial["cohort_status"] == "incomplete"
    assert partial["pending_trials"] == 2
    failed_row = partial["trials"][0]
    assert failed_row["status"] == "completed"
    assert "rate limit" in failed_row["failure"].lower()

    complete = reliability_eval.run_eval(**config, resume_path=out, stop_on_rate_limit=True)

    assert calls == [
        ("task_only", "groq/test", 1),
        ("task_only", "groq/test", 2),
        ("task_only", "groq/test", 3),
    ]
    assert len(complete["trials"]) == 3
    assert complete["trials"][0]["failure"] == failed_row["failure"]
    assert complete["cohort_status"] == "complete"
    assert complete["pending_trials"] == 0


def test_resume_rejects_different_evaluator_sha(tmp_path, monkeypatch):
    monkeypatch.setattr(
        reliability_eval,
        "get_settings",
        lambda: SimpleNamespace(
            effective_enforcement=lambda: "live",
            armoriq_api_key="test-key",
            groq_api_key="test-key",
            database_url="postgresql://unused",
        ),
    )
    artifact = tmp_path / "old-evaluator.json"
    artifact.write_text(
        json.dumps(
            {
                "runner_sha256": "0" * 64,
                "models": ["groq/test"],
                "briefings": ["task_only"],
                "trials_per_group": 2,
                "requested_trials": 2,
                "trials": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="evaluator SHA differs"):
        reliability_eval.run_eval(
            models=["groq/test"], briefings=["task_only"], trials=2, resume_path=artifact
        )


def test_resume_preserves_interruption_history_and_marks_safety_unknown(tmp_path, monkeypatch):
    class FakeDatabase:
        def __init__(self, _dsn):
            pass

        def __enter__(self):
            return self

        def reset_fixture(self):
            pass

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(
        reliability_eval,
        "get_settings",
        lambda: SimpleNamespace(
            effective_enforcement=lambda: "live",
            armoriq_api_key="test-key",
            groq_api_key="test-key",
            database_url="postgresql://unused",
        ),
    )
    monkeypatch.setattr(reliability_eval, "reload_settings", lambda: None)
    monkeypatch.setattr(reliability_eval, "IsolatedEvaluationDatabase", FakeDatabase)
    interruption = {
        "briefing": "task_only",
        "model": "groq/test",
        "trial": 1,
        "status": "interrupted",
        "completed": False,
        "failed": True,
        "failure": "Interrupted by operator.",
        "failure_cause": "cancelled",
    }
    artifact = tmp_path / "interrupted-cohort.json"
    artifact.write_text(
        json.dumps(
            {
                "runner_sha256": reliability_eval._runner_fingerprint()[0],
                "runner_sources": reliability_eval._runner_fingerprint()[1],
                "models": ["groq/test"],
                "briefings": ["task_only"],
                "trials_per_group": 2,
                "trial_groups": 1,
                "requested_trials": 2,
                "trials": [interruption],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        reliability_eval,
        "_run_trial",
        lambda model, briefing, trial, _timeout: {
            "briefing": briefing,
            "model": model,
            "trial": trial,
            "status": "completed",
            "completed": True,
            "failed": False,
            "attempted_restore": 0,
            "forbidden_effects": 0,
            "evidence_complete": True,
        },
    )

    result = reliability_eval.run_eval(
        models=["groq/test"], briefings=["task_only"], trials=2, resume_path=artifact
    )

    assert result["interrupted_attempts"] == [interruption]
    assert result["interrupted_attempt_count"] == 1
    assert len(result["trials"]) == 2
    assert result["summary"]["task_only|groq/test"]["trials"] == 2
    assert result["summary"]["task_only|groq/test"]["interrupted_attempts"] == 1
    assert result["summary"]["task_only|groq/test"]["forbidden_effects"] is None
    assert result["summary"]["task_only|groq/test"]["unknown_safety_trials"] == 1
