"""Build the /system/status document (also used by ``cli status``).

Everything the UI needs to label modes honestly: ArmorIQ live vs simulated,
scripted vs LLM planner, database health and human-readable warnings.
"""

from __future__ import annotations

import logging
from typing import Any

from rewindsafe.api.settings_access import get_settings
from rewindsafe.contracts import CONTRACT_VERSION
from rewindsafe.runtime import armoriq_gateway, db, grants

log = logging.getLogger("rewindsafe.api")

DEFAULT_SESSION_SECRET = "change-me-local-dev-only"


def _warn(level: str, code: str, message: str) -> dict[str, str]:
    return {"level": level, "code": code, "message": message}


GROQ_LABELS = {"openai/gpt-oss-120b": "gpt-oss-120b"}


def planner_label(provider: str | None, model: str | None) -> str:
    if not provider:
        return "Scripted re-enactment (deterministic, no LLM)"
    nice = {"groq": "Groq", "anthropic": "Anthropic", "openai": "OpenAI"}.get(provider, provider)
    short = GROQ_LABELS.get(model or "", (model or "").split("/")[-1])
    return f"Live LLM - {nice} {short}".strip()


def planner_info(settings: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Describe the planner ``auto`` resolves to (anthropic -> groq -> openai -> scripted)."""
    keys = {
        "anthropic": bool(getattr(settings, "anthropic_api_key", "")),
        "groq": bool(getattr(settings, "groq_api_key", "")),
        "openai": bool(getattr(settings, "openai_api_key", "")),
    }
    models = {
        "anthropic": getattr(settings, "anthropic_model", ""),
        "groq": getattr(settings, "groq_model", "openai/gpt-oss-120b"),
        "openai": getattr(settings, "openai_model", ""),
    }
    available = [p for p in ("anthropic", "groq", "openai") if keys[p]]
    preference = getattr(settings, "planner", "auto")
    warnings: list[dict[str, str]] = []
    provider: str | None = None
    if preference != "scripted" and available:
        provider = available[0]
    if provider is None:
        if preference == "scripted":
            warnings.append(_warn("info", "planner_scripted", "Agent uses the scripted planner (REWINDSAFE_PLANNER=scripted)"))
        else:
            warnings.append(_warn("info", "planner_scripted", "Agent uses the scripted planner (no LLM key configured)"))
        if preference == "llm":
            warnings.append(_warn("warn", "llm_unavailable",
                                  "REWINDSAFE_PLANNER=llm but no LLM key is configured; the LLM planner is unavailable"))
        info: dict[str, Any] = {"kind": "scripted", "name": "scripted", "provider": None, "model": None}
    else:
        model = models[provider]
        info = {"kind": "llm", "name": f"{provider}:{model}", "provider": provider, "model": model}
    info["label"] = planner_label(info["provider"], info["model"])
    info["configured_llm"] = bool(available)
    info["available_providers"] = available
    return info, warnings


def _database() -> tuple[bool, int | None]:
    try:
        with db.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True, grants.current_generation()
    except Exception:  # health probe: any failure means "not ok"
        log.warning("Database health check failed", exc_info=True)
        return False, None


def _readiness() -> dict[str, Any] | None:
    """Cached gateway readiness (never raises, never blocks on the network)."""
    try:
        fn = getattr(armoriq_gateway.get_gateway(), "readiness", None)
        return fn() if callable(fn) else None
    except Exception:  # readiness is advisory
        log.warning("Gateway readiness unavailable", exc_info=True)
        return None


def _enforcement(settings: Any, warnings: list[dict[str, str]]) -> dict[str, Any]:
    try:
        described = armoriq_gateway.get_gateway().describe()
    except Exception as exc:  # fail loudly in status rather than invent a mode
        warnings.append(_warn("error", "gateway_unavailable", f"ArmorIQ gateway is unavailable: {type(exc).__name__}"))
        return {
            "mode": settings.effective_enforcement(),
            "simulated": settings.effective_enforcement() != "live",
            "sdk_version": None,
            "session_mode": getattr(settings, "armoriq_session_mode", None),
            "env": getattr(settings, "armoriq_env", None),
            "configured": bool(getattr(settings, "armoriq_api_key", "")),
            "user_email_set": bool(getattr(settings, "armoriq_user_email", "")),
        }
    enforcement = {
        "mode": described.get("mode"),
        "simulated": bool(described.get("simulated")),
        "sdk_version": described.get("sdk_version"),
        "session_mode": described.get("session_mode"),
        "env": described.get("env"),
        "configured": bool(described.get("configured")),
        "user_email_set": bool(described.get("user_email")),
        "readiness": _readiness(),
    }
    if enforcement["simulated"]:
        if not getattr(settings, "armoriq_api_key", ""):
            warnings.append(_warn("warn", "enforcement_simulated", "ArmorIQ enforcement is SIMULATED (no ARMORIQ_API_KEY)"))
        else:
            warnings.append(_warn("warn", "enforcement_simulated", "ArmorIQ enforcement is SIMULATED (REWINDSAFE_ENFORCEMENT=offline)"))
    return enforcement


def build_system_status() -> dict[str, Any]:
    settings = get_settings()
    warnings: list[dict[str, str]] = []
    enforcement = _enforcement(settings, warnings)
    enforcement.setdefault("readiness", None)
    planner, planner_warnings = planner_info(settings)
    warnings.extend(planner_warnings)
    readiness = enforcement.get("readiness") or {}
    if readiness.get("state") == "failed":
        warnings.append(_warn("error", "armoriq_readiness_failed",
                              f"Live ArmorIQ readiness probe failed: {readiness.get('detail') or 'unknown'}"))
    db_ok, generation = _database()
    if not db_ok:
        warnings.append(_warn("error", "database_unreachable", "Database is unreachable"))
    if getattr(settings, "session_secret", "") == DEFAULT_SESSION_SECRET:
        warnings.append(_warn("info", "dev_session_secret",
                              "Session cookies are signed with the default dev secret (local demo only)"))
    return {
        "enforcement": enforcement,
        "planner": planner,
        "database": {"ok": db_ok},
        "fixture_generation": generation,
        "contract_version": CONTRACT_VERSION,
        "warnings": warnings,
    }
