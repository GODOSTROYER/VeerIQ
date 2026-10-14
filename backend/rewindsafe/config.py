"""Application settings (architecture.md section 3).

Settings are read from ``<repo>/.env`` (resolved from this file's location, not
the process working directory) and from the process environment; the
environment wins. The ambient ``ANTHROPIC_BASE_URL`` is deliberately NOT read:
only ``REWINDSAFE_ANTHROPIC_BASE_URL`` configures the Anthropic endpoint.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/rewindsafe/config.py -> parents[0]=rewindsafe, [1]=backend, [2]=repo root
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
ENV_FILE = REPO_ROOT / ".env"

DEFAULT_DATABASE_URL = "postgresql://rewindsafe:rewindsafe@127.0.0.1:5433/rewindsafe"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


class ConfigurationError(RuntimeError):
    """Raised at startup when the configuration is self-contradictory."""


def _env(name: str, default: object) -> object:
    """Field factory: one environment variable name per field, no prefixing."""
    return Field(default=default, validation_alias=AliasChoices(name))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # development keeps the local demo defaults; production refuses demo sign-in and simulated enforcement.
    environment: Literal["development", "showcase", "production"] = _env("REWINDSAFE_ENV", "development")  # type: ignore[assignment]
    database_url: str = _env("DATABASE_URL", DEFAULT_DATABASE_URL)  # type: ignore[assignment]
    session_secret: str = _env("REWINDSAFE_SESSION_SECRET", "change-me-local-dev-only")  # type: ignore[assignment]
    auth_mode: Literal["demo", "oidc"] = _env("REWINDSAFE_AUTH_MODE", "demo")  # type: ignore[assignment]
    cookie_secure: bool = _env("REWINDSAFE_COOKIE_SECURE", False)  # type: ignore[assignment]
    oidc_issuer: str = _env("REWINDSAFE_OIDC_ISSUER", "")  # type: ignore[assignment]
    oidc_client_id: str = _env("REWINDSAFE_OIDC_CLIENT_ID", "")  # type: ignore[assignment]
    oidc_client_secret: str = _env("REWINDSAFE_OIDC_CLIENT_SECRET", "")  # type: ignore[assignment]
    oidc_redirect_uri: str = _env("REWINDSAFE_OIDC_REDIRECT_URI", "")  # type: ignore[assignment]
    oidc_app_origin: str = _env("REWINDSAFE_APP_ORIGIN", "")  # type: ignore[assignment]
    oidc_subjects_json: str = _env("REWINDSAFE_OIDC_SUBJECTS_JSON", "")  # type: ignore[assignment]
    mutation_rate_per_minute: int = _env("REWINDSAFE_MUTATION_RATE_PER_MINUTE", 120)  # type: ignore[assignment]
    login_rate_per_minute: int = _env("REWINDSAFE_LOGIN_RATE_PER_MINUTE", 12)  # type: ignore[assignment]
    import_postgres_allowed_hosts: str = _env("REWINDSAFE_IMPORT_POSTGRES_ALLOWED_HOSTS", "")  # type: ignore[assignment]

    enforcement: Literal["auto", "live", "offline"] = _env("REWINDSAFE_ENFORCEMENT", "auto")  # type: ignore[assignment]
    armoriq_api_key: str = _env("ARMORIQ_API_KEY", "")  # type: ignore[assignment]
    armoriq_env: str = _env("ARMORIQ_ENV", "production")  # type: ignore[assignment]
    armoriq_session_mode: Literal["sdk", "local", "proxy"] = _env("ARMORIQ_SESSION_MODE", "sdk")  # type: ignore[assignment]
    armoriq_user_email: str = _env("ARMORIQ_USER_EMAIL", "")  # type: ignore[assignment]
    armoriq_mcp_name: str = _env("ARMORIQ_MCP_NAME", "rewindsafe-recovery")  # type: ignore[assignment]
    # Default timeout for ArmorIQ HTTP calls. The SDK fixes its own limits for the enforce check (10 s)
    # and plan issuance (30 s); this bounds the remaining calls (audit reports, approval status, plan close).
    armoriq_timeout_s: float = _env("REWINDSAFE_ARMORIQ_TIMEOUT_S", 15.0)  # type: ignore[assignment]
    # Bearer token required by the MCP server's HTTP transport (stdio needs none).
    mcp_token: str = _env("REWINDSAFE_MCP_TOKEN", "")  # type: ignore[assignment]

    planner: str = _env("REWINDSAFE_PLANNER", "auto")  # type: ignore[assignment]
    anthropic_api_key: str = _env("ANTHROPIC_API_KEY", "")  # type: ignore[assignment]
    anthropic_model: str = _env("REWINDSAFE_ANTHROPIC_MODEL", "claude-sonnet-5-5")  # type: ignore[assignment]
    anthropic_base_url: str = _env("REWINDSAFE_ANTHROPIC_BASE_URL", "")  # type: ignore[assignment]
    openai_api_key: str = _env("OPENAI_API_KEY", "")  # type: ignore[assignment]
    openai_model: str = _env("REWINDSAFE_OPENAI_MODEL", "gpt-5.5")  # type: ignore[assignment]

    groq_api_key: str = _env("GROQ_API_KEY", "")  # type: ignore[assignment]
    groq_base_url: str = _env("REWINDSAFE_GROQ_BASE_URL", DEFAULT_GROQ_BASE_URL)  # type: ignore[assignment]
    groq_model: str = _env("REWINDSAFE_GROQ_MODEL", DEFAULT_GROQ_MODEL)  # type: ignore[assignment]
    # Pin the LLM provider used by 'auto'/'llm' selection: auto | anthropic | groq | openai.
    llm_provider: str = _env("REWINDSAFE_LLM_PROVIDER", "auto")  # type: ignore[assignment]

    max_steps: int = _env("REWINDSAFE_MAX_STEPS", 20)  # type: ignore[assignment]
    max_replans: int = _env("REWINDSAFE_MAX_REPLANS", 3)  # type: ignore[assignment]

    # ── derived ────────────────────────────────────────────────────────────

    @property
    def armoriq_configured(self) -> bool:
        return bool(self.armoriq_api_key.strip())

    def effective_enforcement(self) -> Literal["live", "offline"]:
        """``live`` if explicitly requested, or ``auto`` with a key; else ``offline``.

        An explicit ``offline`` always wins, even when a key is present.
        """
        if self.enforcement == "live":
            return "live"
        if self.enforcement == "auto" and self.armoriq_configured:
            return "live"
        return "offline"

    def validate_startup(self) -> None:
        """Fail loudly instead of silently degrading to a simulation."""
        if not 1 <= self.mutation_rate_per_minute <= 10_000 or not 1 <= self.login_rate_per_minute <= 10_000:
            raise ConfigurationError("Rate limits must be between 1 and 10000 requests per minute.")
        if not 1 <= self.armoriq_timeout_s <= 120:
            raise ConfigurationError("REWINDSAFE_ARMORIQ_TIMEOUT_S must be between 1 and 120 seconds.")
        if self.environment == "production":
            if self.auth_mode != "oidc":
                raise ConfigurationError(
                    "REWINDSAFE_ENV=production requires REWINDSAFE_AUTH_MODE=oidc. Demo sign-in lets "
                    "anyone select any identity and is for local use only."
                )
            if self.effective_enforcement() != "live":
                raise ConfigurationError(
                    "REWINDSAFE_ENV=production requires live ArmorIQ enforcement. Set ARMORIQ_API_KEY "
                    "and REWINDSAFE_ENFORCEMENT=live; simulated enforcement is for local use only."
                )
        if self.environment == "showcase":
            # The public judging demo: synthetic data and shared demo identities, but enforcement is
            # never simulated, and the session cookie only travels over HTTPS.
            if self.effective_enforcement() != "live":
                raise ConfigurationError(
                    "REWINDSAFE_ENV=showcase is the public demo and requires live ArmorIQ enforcement. "
                    "Set ARMORIQ_API_KEY and REWINDSAFE_ENFORCEMENT=live."
                )
            if (self.session_secret == "change-me-local-dev-only" or len(self.session_secret) < 32
                    or len(set(self.session_secret)) < 12):
                raise ConfigurationError(
                    "REWINDSAFE_ENV=showcase requires a REWINDSAFE_SESSION_SECRET of at least 32 characters "
                    "with 12 distinct characters."
                )
            if not self.cookie_secure:
                raise ConfigurationError(
                    "REWINDSAFE_ENV=showcase requires REWINDSAFE_COOKIE_SECURE=true (serve it over HTTPS)."
                )
        if self.auth_mode == "oidc":
            required = {
                "REWINDSAFE_OIDC_ISSUER": self.oidc_issuer,
                "REWINDSAFE_OIDC_CLIENT_ID": self.oidc_client_id,
                "REWINDSAFE_OIDC_CLIENT_SECRET": self.oidc_client_secret,
                "REWINDSAFE_OIDC_REDIRECT_URI": self.oidc_redirect_uri,
                "REWINDSAFE_APP_ORIGIN": self.oidc_app_origin,
                "REWINDSAFE_OIDC_SUBJECTS_JSON": self.oidc_subjects_json,
            }
            missing = [name for name, value in required.items() if not str(value).strip()]
            if missing:
                raise ConfigurationError("OIDC authentication is enabled but required settings are missing: " + ", ".join(missing))
            if (self.session_secret == "change-me-local-dev-only" or len(self.session_secret) < 32
                    or len(set(self.session_secret)) < 12):
                raise ConfigurationError("OIDC mode requires a non-default REWINDSAFE_SESSION_SECRET with at least 32 characters and 12 distinct characters.")
            if not self.cookie_secure:
                raise ConfigurationError("OIDC mode requires REWINDSAFE_COOKIE_SECURE=true so the session cookie is sent only over HTTPS.")
            for name, value in (("REWINDSAFE_OIDC_ISSUER", self.oidc_issuer),
                                ("REWINDSAFE_OIDC_REDIRECT_URI", self.oidc_redirect_uri),
                                ("REWINDSAFE_APP_ORIGIN", self.oidc_app_origin)):
                parsed = urlsplit(str(value))
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise ConfigurationError(f"{name} must be a valid HTTPS URL without embedded credentials, query, or fragment.")
            app_origin = urlsplit(self.oidc_app_origin)
            if app_origin.path not in {"", "/"}:
                raise ConfigurationError("REWINDSAFE_APP_ORIGIN must be an origin without an application path.")
            redirect_origin = urlsplit(self.oidc_redirect_uri)
            if (redirect_origin.scheme, redirect_origin.hostname, redirect_origin.port) != (
                app_origin.scheme, app_origin.hostname, app_origin.port
            ):
                raise ConfigurationError("REWINDSAFE_OIDC_REDIRECT_URI must use the same HTTPS origin as REWINDSAFE_APP_ORIGIN.")
            self.oidc_subject_mappings()
        elif self.auth_mode != "demo":
            raise ConfigurationError("REWINDSAFE_AUTH_MODE must be 'demo' or 'oidc'.")
        if self.enforcement == "live" and not self.armoriq_configured:
            raise ConfigurationError(
                "REWINDSAFE_ENFORCEMENT=live but ARMORIQ_API_KEY is not set. Set the key "
                "(get one at https://platform.armoriq.ai/dashboard/api-keys) or use "
                "REWINDSAFE_ENFORCEMENT=offline|auto. RewindSafe never silently falls back "
                "from live to simulated enforcement."
            )

    def oidc_subject_mappings(self) -> dict[str, dict[str, str]]:
        """Return admin-controlled subject-to-identity mappings; never derive authority from claims."""
        if not self.oidc_subjects_json.strip():
            return {}
        try:
            raw = json.loads(self.oidc_subjects_json)
        except json.JSONDecodeError as exc:
            raise ConfigurationError("REWINDSAFE_OIDC_SUBJECTS_JSON must be valid JSON.") from exc
        if not isinstance(raw, dict) or not raw:
            raise ConfigurationError("REWINDSAFE_OIDC_SUBJECTS_JSON must be a non-empty object keyed by issuer subject.")
        required = {"identity_id", "name", "email", "role", "tenant_id", "title", "initials", "color"}
        seen_ids: set[str] = set()
        result: dict[str, dict[str, str]] = {}
        for subject, entry in raw.items():
            if not isinstance(subject, str) or not subject.strip() or not isinstance(entry, dict) or set(entry) != required:
                raise ConfigurationError("Each OIDC subject mapping must provide identity_id, name, email, role, tenant_id, title, initials, and color.")
            if entry["role"] not in {"operator", "reviewer"}:
                raise ConfigurationError(f"OIDC subject {subject!r} has an unsupported role; use operator or reviewer.")
            if any(not isinstance(value, str) or not value.strip() for value in entry.values()):
                raise ConfigurationError(f"OIDC subject {subject!r} has an empty or non-string identity field.")
            if entry["identity_id"] in seen_ids:
                raise ConfigurationError("OIDC mappings must use a distinct identity_id for each issuer subject (required for separation of duties).")
            if not (len(entry["color"]) == 7 and entry["color"].startswith("#") and all(c in "0123456789abcdefABCDEF" for c in entry["color"][1:])):
                raise ConfigurationError(f"OIDC subject {subject!r} has an invalid color; expected #RRGGBB.")
            seen_ids.add(entry["identity_id"])
            result[subject] = entry
        return result

    def anthropic_base_url_effective(self) -> str:
        """Always pass this explicitly to the Anthropic client (ambient env is ignored)."""
        return self.anthropic_base_url.strip() or DEFAULT_ANTHROPIC_BASE_URL


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Drop the cached settings (tests / after editing the environment)."""
    get_settings.cache_clear()
    return get_settings()
