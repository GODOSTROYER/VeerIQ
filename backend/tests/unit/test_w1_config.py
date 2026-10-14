"""W1: settings and effective enforcement (no database)."""

from __future__ import annotations

import pytest

from rewindsafe.config import DEFAULT_ANTHROPIC_BASE_URL, ConfigurationError, Settings


def make(monkeypatch, **env) -> Settings:
    for k in (
        "REWINDSAFE_ENFORCEMENT",
        "ARMORIQ_API_KEY",
        "ANTHROPIC_BASE_URL",
        "REWINDSAFE_ANTHROPIC_BASE_URL",
        "DATABASE_URL",
        "REWINDSAFE_MAX_STEPS",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_defaults(monkeypatch):
    s = make(monkeypatch)
    assert s.database_url.endswith("127.0.0.1:5433/rewindsafe")
    assert s.enforcement == "auto" and s.armoriq_session_mode == "sdk"
    assert s.armoriq_mcp_name == "rewindsafe-recovery"
    assert s.max_steps == 20 and s.max_replans == 3 and s.anthropic_model == "claude-sonnet-5-5"
    assert s.effective_enforcement() == "offline"


@pytest.mark.parametrize(
    ("mode", "key", "expected"),
    [
        ("auto", "", "offline"),
        ("auto", "ak_test_x", "live"),
        ("offline", "ak_test_x", "offline"),
        ("live", "ak_test_x", "live"),
        ("live", "", "live"),
    ],
)
def test_effective_enforcement(monkeypatch, mode, key, expected):
    s = make(monkeypatch, REWINDSAFE_ENFORCEMENT=mode, ARMORIQ_API_KEY=key)
    assert s.effective_enforcement() == expected


def test_live_without_key_fails_loudly_never_falls_back(monkeypatch):
    s = make(monkeypatch, REWINDSAFE_ENFORCEMENT="live")
    with pytest.raises(ConfigurationError, match="ARMORIQ_API_KEY"):
        s.validate_startup()
    make(monkeypatch, REWINDSAFE_ENFORCEMENT="auto").validate_startup()  # auto without key is fine (offline)


def test_ambient_anthropic_base_url_is_ignored(monkeypatch):
    s = make(monkeypatch, ANTHROPIC_BASE_URL="http://evil.example")
    assert s.anthropic_base_url == "" and s.anthropic_base_url_effective() == DEFAULT_ANTHROPIC_BASE_URL
    s2 = make(monkeypatch, REWINDSAFE_ANTHROPIC_BASE_URL="http://proxy.local")
    assert s2.anthropic_base_url_effective() == "http://proxy.local"


def test_env_overrides_numeric_fields(monkeypatch):
    assert make(monkeypatch, REWINDSAFE_MAX_STEPS="7").max_steps == 7


def test_production_profile_refuses_demo_sign_in(monkeypatch):
    s = make(monkeypatch, REWINDSAFE_ENV="production", ARMORIQ_API_KEY="ak_test_x", REWINDSAFE_ENFORCEMENT="live")
    with pytest.raises(ConfigurationError, match="REWINDSAFE_AUTH_MODE=oidc"):
        s.validate_startup()


@pytest.mark.parametrize(("mode", "key"), [("offline", "ak_test_x"), ("auto", "")])
def test_production_profile_refuses_simulated_enforcement(monkeypatch, mode, key):
    s = make(
        monkeypatch,
        REWINDSAFE_ENV="production",
        REWINDSAFE_AUTH_MODE="oidc",
        REWINDSAFE_ENFORCEMENT=mode,
        ARMORIQ_API_KEY=key,
    )
    with pytest.raises(ConfigurationError, match="live ArmorIQ enforcement"):
        s.validate_startup()


SHOWCASE = {
    "REWINDSAFE_ENV": "showcase",
    "ARMORIQ_API_KEY": "ak_test_x",
    "REWINDSAFE_ENFORCEMENT": "live",
    "REWINDSAFE_SESSION_SECRET": "showcase-secret-0123456789-abcdefghij",
    "REWINDSAFE_COOKIE_SECURE": "true",
}


def test_showcase_profile_allows_demo_sign_in_with_live_enforcement(monkeypatch):
    s = make(monkeypatch, **SHOWCASE)
    assert s.environment == "showcase" and s.auth_mode == "demo"
    s.validate_startup()


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"REWINDSAFE_ENFORCEMENT": "offline"}, "live ArmorIQ enforcement"),
        ({"REWINDSAFE_ENFORCEMENT": "auto", "ARMORIQ_API_KEY": ""}, "live ArmorIQ enforcement"),
        ({"REWINDSAFE_SESSION_SECRET": "change-me-local-dev-only"}, "REWINDSAFE_SESSION_SECRET"),
        ({"REWINDSAFE_COOKIE_SECURE": "false"}, "REWINDSAFE_COOKIE_SECURE"),
    ],
)
def test_showcase_profile_refuses_simulation_and_weak_sessions(monkeypatch, override, message):
    s = make(monkeypatch, **{**SHOWCASE, **override})
    with pytest.raises(ConfigurationError, match=message):
        s.validate_startup()


def test_development_profile_keeps_local_defaults(monkeypatch):
    s = make(monkeypatch)
    assert s.environment == "development" and s.armoriq_timeout_s == 15.0 and s.mcp_token == ""
    s.validate_startup()


@pytest.mark.parametrize("value", ["0", "0.5", "121"])
def test_armoriq_timeout_must_be_bounded(monkeypatch, value):
    s = make(monkeypatch, REWINDSAFE_ARMORIQ_TIMEOUT_S=value)
    with pytest.raises(ConfigurationError, match="REWINDSAFE_ARMORIQ_TIMEOUT_S"):
        s.validate_startup()
