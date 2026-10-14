"""ArmorIQ enforcement gateway (architecture.md 4.8).

Two implementations of one protocol:

* :class:`LiveArmorIQGateway` - the real ``armoriq-sdk`` (read from the installed
  0.6.10 source): a signed intent plan per run, ``session.check`` per action,
  ``await_approval`` for HOLDs, ``report`` for audit. Fail closed everywhere.
* :class:`OfflineSimulatedGateway` - a deterministic SIMULATION with the same
  semantics. Every decision it produces carries ``simulated=True`` and source
  ``armoriq.offline_simulation`` and must never be presented as ArmorIQ evidence.

Honesty notes encoded here (see also ``docs`` and ``armoriq/README.md``):

* The SDK path used (``sdk`` session mode, ``/iap/sdk/enforce``) binds TOOL NAMES
  to the signed plan. It does not bind arguments or resources to the plan; that
  is enforced by RewindSafe's immutable manifests and grant scope.
* ``session.report`` swallows errors. Delivery is therefore tracked in
  ``runtime.telemetry_outbox`` and verified from the HTTP status of the audit POST
  (observed through an httpx response hook) rather than assumed.
* In ``sdk`` mode the SDK does not expose the HTTP status of ``/iap/sdk/enforce``. An httpx
  response hook records it per thread so 401/429/5xx are reclassified UNAVAILABLE (fail closed,
  not a policy denial) instead of a plain ``block``.
* LIVE-OBSERVED (2026-10-07, docs/architecture.md 1.1): a wider plan including
  ``restore_access_grant`` IS issued; the org allowlist then blocks it at ``check``
  (``tool_not_in_allowlist``). No HOLD threshold is configured in the live workspace. The offline
  simulation mirrors exactly this observed behavior and nothing stronger.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any, Literal, Protocol

from psycopg.types.json import Jsonb

from rewindsafe.config import Settings, get_settings
from rewindsafe.contracts import (
    Actor,
    Decision,
    DecisionSource,
    Outcome,
    PlanBinding,
    SponsorDetail,
    TaskGrant,
)
from rewindsafe.runtime import db, events
from rewindsafe.runtime.adapter import make_decision
from rewindsafe.runtime.canonical import digest, new_id, redact_secrets, redact_text, utcnow

log = logging.getLogger(__name__)

PLAN_VALIDITY_SECONDS = 1800
READINESS_TTL_S = 600
SIM_HOLD_ENV = "REWINDSAFE_SIM_HOLD_THRESHOLD"
DEFAULT_DENY_WINDOW_S = 600
ORG_ALLOWLIST_REASON = "tool_not_in_allowlist"
SIM_ALLOWLIST_REASON = "tool_not_in_allowlist (simulated org policy from armoriq/armoriq.yaml)"
OFFLINE_DENIED_TOOLS = frozenset({"restore_access_grant"})
OFFLINE_HOLD_TOOL = "apply_repair_manifest"
GATE_ACTIONS = ("allow", "block", "hold")
ApprovalResult = Literal["approved", "rejected", "timeout"]


def sdk_version() -> str | None:
    try:
        from armoriq_sdk._version import __version__

        return __version__
    except Exception:  # pragma: no cover - SDK missing
        return None


def _short(ref: str | None) -> str:
    if not ref:
        return "unknown"
    ref = ref.split(":", 1)[-1]
    return ref[:8] + "…"


def _args_evidence(tool: str, args: dict) -> dict[str, Any]:
    """What was sent to ArmorIQ, without echoing the values."""
    safe = redact_secrets(args)
    return {"arguments_digest": digest({"tool": tool, "args": safe}), "argument_keys": sorted(safe.keys())}


# ─── classification (pure) ────────────────────────────────────────────────


@dataclass(frozen=True)
class Classified:
    source: DecisionSource
    outcome: Outcome
    reason: str
    invariant: str | None = None


def classify_enforce_result(result: Any, *, require_delegation_for_hold: bool = True) -> Classified:
    """Map an SDK ``EnforceResult`` to (source, outcome, reason). Fails closed.

    * reason ``tool-not-in-plan*``  -> plan-binding BLOCK (no network call was made)
    * reason ``enforce-unavailable*`` -> UNAVAILABLE (never a policy denial)
    * action must be exactly ``allow`` / ``block`` / ``hold``; anything else -> BLOCK
    * ``allow`` additionally requires ``allowed is True``
    * ``hold`` without a delegation id cannot be approved -> UNAVAILABLE (fail closed)
    """
    raw_action = getattr(result, "action", None)
    allowed = getattr(result, "allowed", None)
    reason = redact_text(str(getattr(result, "reason", None) or "")).strip()
    delegation_id = getattr(result, "delegation_id", None)

    if reason.startswith("tool-not-in-plan"):
        return Classified(
            DecisionSource.ARMORIQ_PLAN_BINDING,
            Outcome.BLOCK,
            reason or "tool-not-in-plan",
            "tool_not_in_signed_plan",
        )
    if reason.startswith("enforce-unavailable"):
        return Classified(
            DecisionSource.ARMORIQ_ENFORCE,
            Outcome.UNAVAILABLE,
            "ArmorIQ enforcement could not be reached; refused (fail closed). " + reason,
            "enforcement_unavailable",
        )
    if raw_action == "allow":
        if allowed is True:
            if reason.startswith("Allowed by approved delegation"):
                return Classified(
                    DecisionSource.ARMORIQ_ENFORCE,
                    Outcome.ALLOW,
                    reason,
                    "armoriq_delegation_consumed",
                )
            return Classified(
                DecisionSource.ARMORIQ_ENFORCE, Outcome.ALLOW, reason or "Allowed by ArmorIQ policy."
            )
        return Classified(
            DecisionSource.ARMORIQ_ENFORCE,
            Outcome.BLOCK,
            "ArmorIQ returned an inconsistent answer (action=allow but allowed is not true); refused.",
            "inconsistent_enforcement_response",
        )
    if raw_action == "hold":
        if allowed is True:
            return Classified(
                DecisionSource.ARMORIQ_ENFORCE,
                Outcome.BLOCK,
                "ArmorIQ returned an inconsistent answer (action=hold but allowed=true); refused.",
                "inconsistent_enforcement_response",
            )
        if require_delegation_for_hold and not delegation_id:
            return Classified(
                DecisionSource.ARMORIQ_ENFORCE,
                Outcome.UNAVAILABLE,
                "ArmorIQ asked for approval (hold) but no delegation request could be created, so the "
                "approval cannot be recorded; refused (fail closed). " + reason,
                "hold_without_delegation",
            )
        return Classified(
            DecisionSource.ARMORIQ_ENFORCE,
            Outcome.HOLD,
            reason or "ArmorIQ policy requires approval.",
            "armoriq_hold",
        )
    if raw_action == "block":
        low = reason.lower()
        if "no_matching_policy" in low:
            return Classified(
                DecisionSource.ARMORIQ_ENFORCE,
                Outcome.BLOCK,
                "ArmorIQ default-deny: no workspace policy matches this agent/tool "
                "(register armoriq/armoriq.yaml). " + reason,
                "armoriq_default_deny",
            )
        if ORG_ALLOWLIST_REASON in low:
            return Classified(
                DecisionSource.ARMORIQ_ENFORCE, Outcome.BLOCK, reason, "org_policy_allowlist"
            )
        return Classified(
            DecisionSource.ARMORIQ_ENFORCE,
            Outcome.BLOCK,
            reason or "Blocked by ArmorIQ policy.",
            "armoriq_policy",
        )
    return Classified(
        DecisionSource.ARMORIQ_ENFORCE,
        Outcome.BLOCK,
        f"ArmorIQ returned an unrecognized enforcement action ({str(raw_action)[:40]!r}); refused (fail closed).",
        "unknown_enforcement_action",
    )


def _utc_from_ts(ts: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


# ─── protocol ─────────────────────────────────────────────────────────────


class EnforcementGateway(Protocol):
    mode: Literal["live", "offline"]

    def describe(self) -> dict: ...

    def bind_plan(
        self, run_id: str, grant: TaskGrant, tool_calls: list[dict], user_email: str, *, llm: str = ...
    ) -> PlanBinding: ...

    def check(self, run_id: str, proposal_id: str, tool: str, canonical_args: dict) -> Decision: ...

    def await_sponsor_approval(
        self, run_id: str, delegation_id: str, timeout_s: float, cancel: threading.Event | None = None
    ) -> ApprovalResult: ...

    def report(
        self, run_id: str, proposal_id: str, tool: str, args: dict, result_summary: dict, status: str
    ) -> None: ...

    def probe_wider_plan(
        self, run_id: str, grant: TaskGrant, extra_tools: list[str], user_email: str
    ) -> Decision: ...

    def close_run(self, run_id: str, outcome: str | None = None) -> None: ...

    def readiness(self) -> dict: ...

    def record_generation(
        self,
        run_id: str,
        model: str,
        input_tokens: float,
        output_tokens: float,
        finish_reason: str | None = None,
    ) -> None: ...

    def shadow_backend_check(
        self, run_id: str, proposal_id: str | None, tool: str, canonical_args: dict
    ) -> Decision | None: ...

    def force_unavailable(self, flag: bool) -> None: ...


# ─── outbox helpers ───────────────────────────────────────────────────────


def _outbox_insert(
    run_id: str, proposal_id: str | None, payload: dict, status: str, error: str | None
) -> int:
    with db.autocommit_connection() as conn:
        row = conn.execute(
            "INSERT INTO runtime.telemetry_outbox (run_id, proposal_id, kind, payload, status, last_error) "
            "VALUES (%s, %s, 'armoriq.report', %s, %s, %s) RETURNING outbox_id",
            (run_id, proposal_id, Jsonb(payload), status, error),
        ).fetchone()
    return int(row["outbox_id"])


def _outbox_finish(outbox_id: int, status: str, error: str | None) -> None:
    with db.autocommit_connection() as conn:
        conn.execute(
            "UPDATE runtime.telemetry_outbox SET status = %s, last_error = %s, attempts = attempts + 1, "
            "updated_at = now() WHERE outbox_id = %s",
            (status, error, outbox_id),
        )


def _report_payload(tool: str, args: dict, result_summary: dict, status: str) -> dict:
    return redact_secrets(
        {
            "tool": tool,
            "status": status,
            **_args_evidence(tool, args),
            "result_summary": result_summary,
        }
    )


def _validated_audit_id(value: Any) -> str | None:
    """Accept only a canonical UUID-shaped audit identifier from the service acknowledgement."""
    if not isinstance(value, str) or len(value) != 36:
        return None
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return None
    normalized = str(parsed)
    return normalized if normalized == value.lower() else None


# ─── live ─────────────────────────────────────────────────────────────────


def _policy_names(token: Any, pv: dict) -> list[str]:
    names: list[str] = []
    entries = list(getattr(token, "policy_snapshot", None) or [])
    entries += list(pv.get("matched_policies") or []) if isinstance(pv, dict) else []
    for entry in entries:
        n = None
        if isinstance(entry, dict):
            n = entry.get("policyName") or entry.get("policy_name") or entry.get("name")
        elif isinstance(entry, str):
            n = entry
        if n and str(n)[:120] not in names:
            names.append(str(n)[:120])
    return names



@dataclass
class _RunState:
    session: Any = None
    binding: PlanBinding | None = None
    user_email: str = ""
    error_kind: str | None = None  # "policy" | "unavailable" when no plan could be bound
    bind_decision: Decision | None = None
    holds: dict[str, str] = field(default_factory=dict)  # delegation_id -> action digest
    approved: dict[str, str] = field(default_factory=dict)  # action digest -> approved delegation_id
    wider: dict[str, Decision] = field(default_factory=dict)  # tool -> org-allowlist evidence (cached per run)
    shadow_session: Any = None
    shadow_binding: PlanBinding | None = None
    shadow_lock: threading.Lock = field(default_factory=threading.Lock)
    observability_session_id: str | None = None


class LiveArmorIQGateway:
    """Real ArmorIQ SDK gateway (strategy 2: ArmorIQ decides, our dispatcher executes)."""

    mode: Literal["live", "offline"] = "live"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_factory = client_factory or self._default_client_factory
        self._client: Any = None
        self._client_lock = threading.Lock()
        self._bind_lock = threading.Lock()  # SDK keeps user_email_override on the shared client
        self._runs: dict[str, _RunState] = {}
        self._runs_lock = threading.Lock()
        self._force_unavailable = False
        self._tls = threading.local()  # last audit/enforce/plan-status HTTP status seen by this thread
        self._obs_status: int | None = None  # last HTTP status of an observability span POST (any thread)
        self._default_deny_seen: list[float] = []
        self._readiness: dict[str, Any] = {
            "state": "unverified",
            "checked_at": None,
            "detail": "ArmorIQ has not been probed yet in this process.",
            "matched_policy": None,
            "plan_latency_ms": None,
            "check_latency_ms": None,
        }
        self._readiness_lock = threading.Lock()
        self._readiness_thread: threading.Thread | None = None
        self._readiness_attempt_at: float | None = None

    # -- plumbing -----------------------------------------------------------

    @property
    def client(self) -> Any:
        """The (lazily created) ``ArmorIQClient``. Construction performs a network health check."""
        with self._client_lock:
            if self._client is None:
                self._client = self._client_factory()
            return self._client

    def _default_client_factory(self) -> Any:
        import os

        from armoriq_sdk import ArmorIQClient

        # The SDK resolves its endpoints from the PROCESS environment; mirror the configured value.
        os.environ.setdefault("ARMORIQ_ENV", self._settings.armoriq_env)
        client = ArmorIQClient(
            api_key=self._settings.armoriq_api_key.strip(),
            use_production=True,
            timeout=self._settings.armoriq_timeout_s,
        )
        self._install_audit_hook(client)
        return client

    def _install_audit_hook(self, client: Any) -> None:
        tls = self._tls

        def _hook(response: Any) -> None:
            try:
                path = str(response.request.url.path)
                if path.endswith("/iap/audit"):
                    tls.audit_status = response.status_code
                    tls.audit_id = None
                    if response.status_code == 200:
                        try:
                            response.read()
                            body = response.json()
                            if isinstance(body, dict):
                                tls.audit_id = _validated_audit_id(body.get("audit_id"))
                        except Exception:  # malformed/empty acknowledgements must not affect reporting
                            pass
                elif path.endswith("/iap/sdk/enforce"):
                    tls.enforce_status = response.status_code
                elif path.endswith("/status") and "/iap/plans/" in path:
                    tls.plan_status = response.status_code
                elif path.endswith("/observability/spans"):
                    self._obs_status = response.status_code
            except Exception:  # pragma: no cover - never break the SDK call
                pass

        try:
            client.http_client.event_hooks["response"].append(_hook)
        except Exception:  # pragma: no cover
            log.warning("could not install response hook; delivery/enforce status will be unverified")

    def _email(self, user_email: str) -> str:
        return (self._settings.armoriq_user_email or user_email or "").strip().lower()

    def _state(self, run_id: str) -> _RunState | None:
        with self._runs_lock:
            return self._runs.get(run_id)

    def _put_state(self, run_id: str, state: _RunState) -> None:
        with self._runs_lock:
            self._runs[run_id] = state

    def attach_session_for_tests(
        self,
        run_id: str,
        session: Any,
        binding: PlanBinding | None = None,
        user_email: str = "test@example.com",
    ) -> None:
        """Test hook: register a fake session for ``run_id`` (no network)."""
        self._put_state(run_id, _RunState(session=session, binding=binding, user_email=user_email))

    def force_unavailable(self, flag: bool) -> None:
        self._force_unavailable = bool(flag)

    def describe(self) -> dict:
        return {
            "mode": "live",
            "simulated": False,
            "sdk_version": sdk_version(),
            "session_mode": self._settings.armoriq_session_mode,
            "env": self._settings.armoriq_env,
            "configured": self._settings.armoriq_configured,
            "user_email": self._settings.armoriq_user_email,
            "observability": {"enabled": True, "last_spans_http_status": self._obs_status},
            "default_deny_recent": self.default_deny_recent(),
        }

    def default_deny_recent(self) -> bool:
        """True when ArmorIQ answered ``no_matching_policy`` in the last 10 minutes (workspace not registered)."""
        cutoff = time.monotonic() - DEFAULT_DENY_WINDOW_S
        with self._runs_lock:
            self._default_deny_seen = [t for t in self._default_deny_seen if t >= cutoff]
            return bool(self._default_deny_seen)

    def observability_session_id(self, run_id: str) -> str | None:
        st = self._state(run_id)
        return st.observability_session_id if st else None

    def _sponsor(self, state: _RunState | None, *, raw_action: str | None = None, **kw: Any) -> SponsorDetail:
        b = state.binding if state else None
        return SponsorDetail(
            mode="live",
            session_mode=self._settings.armoriq_session_mode,
            sdk_version=sdk_version(),
            raw_action=raw_action,
            plan_id=b.plan_id if b else None,
            plan_hash=b.plan_hash if b else None,
            token_id=b.token_id if b else None,
            **kw,
        )

    # -- plan ---------------------------------------------------------------

    def bind_plan(
        self,
        run_id: str,
        grant: TaskGrant,
        tool_calls: list[dict],
        user_email: str,
        *,
        llm: str = "rewindsafe-agent",
    ) -> PlanBinding:
        return self.bind_plan_with_decision(run_id, grant, tool_calls, user_email, llm=llm)[0]

    def bind_plan_with_decision(
        self,
        run_id: str,
        grant: TaskGrant,
        tool_calls: list[dict],
        user_email: str,
        *,
        llm: str = "rewindsafe-agent",
    ) -> tuple[PlanBinding, Decision]:
        """Mint the signed plan for a run. Returns the binding plus the issuance decision
        (ALLOW when signed; BLOCK/ARMORIQ_TOKEN_ISSUANCE when org policy refused; UNAVAILABLE otherwise)."""
        steps = [str(tc["name"]) for tc in tool_calls]
        email = self._email(user_email)
        t0 = time.perf_counter()
        base = dict(
            mode="live",
            simulated=False,
            steps=steps,
            sdk_version=sdk_version(),
            session_mode=self._settings.armoriq_session_mode,
        )
        state = _RunState(user_email=email)
        session = None
        try:
            from armoriq_sdk.session import SessionOptions

            client = self.client
            with self._bind_lock:
                session = client.for_user(email).start_session(
                    SessionOptions(
                        mode=self._settings.armoriq_session_mode,
                        default_mcp_name=self._settings.armoriq_mcp_name,
                        validity_seconds=PLAN_VALIDITY_SECONDS,
                        llm=llm,
                    )
                )
                client.user_email_override = email
                token = session.start_plan(tool_calls, goal=grant.purpose)
        except Exception as exc:  # noqa: BLE001 - classified below
            latency = (time.perf_counter() - t0) * 1000
            blocked = type(exc).__name__ == "PolicyBlockedException"
            if session is not None:
                _safe_close(session)
            msg = redact_text(f"{type(exc).__name__}: {exc}")[:400]
            if blocked:
                meta = getattr(exc, "metadata", None) or {}
                reason = redact_text(str(getattr(exc, "reason", "") or "Blocked by policy"))[:400]
                state.error_kind = "policy"
                binding = PlanBinding(**base, error=f"ArmorIQ refused to sign the plan: {reason}")
                decision = make_decision(
                    run_id,
                    DecisionSource.ARMORIQ_TOKEN_ISSUANCE,
                    Outcome.BLOCK,
                    f"ArmorIQ refused to sign the recovery plan: {reason}",
                    invariant="plan_issuance_refused",
                    decisive=True,
                    latency_ms=latency,
                    sponsor=self._sponsor(
                        None,
                        raw_action=str(getattr(exc, "enforcement_action", "") or "") or None,
                        sanitized_response=redact_secrets(
                            {
                                "denied_tools": meta.get("denied_tools"),
                                "denied_reasons": meta.get("denied_reasons"),
                                "default_enforcement_action": meta.get("default_enforcement_action"),
                            }
                        ),
                    ),
                    evidence={"tools": steps},
                )
            else:
                state.error_kind = "unavailable"
                binding = PlanBinding(**base, error=f"ArmorIQ plan issuance failed: {msg}")
                decision = make_decision(
                    run_id,
                    DecisionSource.ARMORIQ_TOKEN_ISSUANCE,
                    Outcome.UNAVAILABLE,
                    "ArmorIQ could not issue a signed plan; no action can run (fail closed). " + msg,
                    invariant="plan_issuance_unavailable",
                    decisive=True,
                    latency_ms=latency,
                    sponsor=self._sponsor(None, sanitized_response={"error": msg}),
                    evidence={"tools": steps},
                )
            state.binding = binding
            state.bind_decision = decision
            self._put_state(run_id, state)
            return binding, decision

        latency = (time.perf_counter() - t0) * 1000
        pv = getattr(token, "policy_validation", None) or {}
        binding = PlanBinding(
            **base,
            plan_id=getattr(token, "plan_id", None),
            plan_hash=getattr(token, "plan_hash", None),
            token_id=getattr(token, "token_id", None),
            issued_at=_utc_from_ts(getattr(token, "issued_at", None)),
            expires_at=_utc_from_ts(getattr(token, "expires_at", None)),
            latency_ms=latency,
            matched_policies=_policy_names(token, pv),
        )
        state.session = session
        state.observability_session_id = getattr(session, "session_id", None)
        state.binding = binding
        sanitized = redact_secrets(
            {
                "allowed_tools": pv.get("allowed_tools"),
                "denied_tools": pv.get("denied_tools"),
                "default_enforcement_action": pv.get("default_enforcement_action"),
                "total_steps": getattr(token, "total_steps", None),
                "policy_snapshot_entries": len(getattr(token, "policy_snapshot", None) or []),
                "matched_policies": binding.matched_policies,
                "observability_session_id": state.observability_session_id,
            }
        )
        decision = make_decision(
            run_id,
            DecisionSource.ARMORIQ_TOKEN_ISSUANCE,
            Outcome.ALLOW,
            f"ArmorIQ signed the recovery plan ({len(steps)} tools, plan {_short(binding.plan_hash)}).",
            latency_ms=latency,
            sponsor=self._sponsor(state, sanitized_response=sanitized),
            evidence={"tools": steps},
        )
        state.bind_decision = decision
        self._put_state(run_id, state)
        return binding, decision

    def get_bind_decision(self, run_id: str) -> Decision | None:
        st = self._state(run_id)
        return st.bind_decision if st else None

    # -- check --------------------------------------------------------------

    def check(self, run_id: str, proposal_id: str, tool: str, canonical_args: dict) -> Decision:
        t0 = time.perf_counter()
        state = self._state(run_id)
        evidence = _args_evidence(tool, canonical_args)

        def done(c: Classified, *, raw: Any = None, extra: dict | None = None) -> Decision:
            latency = (time.perf_counter() - t0) * 1000
            delegation_id = getattr(raw, "delegation_id", None) if raw is not None else None
            obligations = (
                redact_secrets(list(getattr(raw, "obligations", None) or [])) if raw is not None else []
            )
            matched = getattr(raw, "matched_policy", None) if raw is not None else None
            sponsor = self._sponsor(
                state,
                raw_action=getattr(raw, "action", None) if raw is not None else None,
                matched_policy=matched,
                delegation_id=delegation_id,
                obligations=[o if isinstance(o, dict) else {"value": o} for o in obligations],
                sanitized_response=redact_secrets(
                    {
                        "allowed": getattr(raw, "allowed", None) if raw is not None else None,
                        "action": getattr(raw, "action", None) if raw is not None else None,
                        "reason": c.reason,
                        "matched_policy": matched,
                        "delegation_id": delegation_id,
                        "obligation_count": len(obligations),
                        **(extra or {}),
                    }
                ),
            )
            return make_decision(
                run_id,
                c.source,
                c.outcome,
                c.reason,
                proposal_id=proposal_id,
                invariant=c.invariant,
                latency_ms=latency,
                sponsor=sponsor,
                evidence={
                    **evidence,
                    "argument_binding": "ArmorIQ SDK binds tool names to the signed plan; arguments are not bound by it.",
                },
            )

        if self._force_unavailable:
            return done(
                Classified(
                    DecisionSource.ARMORIQ_ENFORCE,
                    Outcome.UNAVAILABLE,
                    "ArmorIQ enforcement is unavailable (forced for testing); refused (fail closed).",
                    "enforcement_unavailable",
                )
            )
        if state is None or state.session is None:
            if state is not None and state.error_kind == "policy":
                return done(
                    Classified(
                        DecisionSource.ARMORIQ_TOKEN_ISSUANCE,
                        Outcome.BLOCK,
                        "No signed plan exists for this run: ArmorIQ refused to issue it.",
                        "plan_issuance_refused",
                    )
                )
            return done(
                Classified(
                    DecisionSource.ARMORIQ_ENFORCE,
                    Outcome.UNAVAILABLE,
                    "No ArmorIQ session/plan is bound for this run; refused (fail closed).",
                    "no_signed_plan",
                )
            )
        key = digest({"tool": tool, "args": canonical_args})
        raw, c = self._session_check(state, tool, canonical_args)
        if raw is None:
            return done(c)
        if c.invariant == "armoriq_default_deny":
            with self._runs_lock:
                self._default_deny_seen.append(time.monotonic())
        if c.outcome == Outcome.HOLD:
            delegation_id = getattr(raw, "delegation_id", None)
            if delegation_id:
                state.holds[str(delegation_id)] = key
            if key in state.approved:
                # The sponsor delegation for exactly this action was approved (status verified via
                # get_delegation_status). The SDK's reuse path did not consume it; do not open a NEW hold.
                did = state.approved.pop(key)
                return done(
                    Classified(
                        DecisionSource.ARMORIQ_APPROVAL,
                        Outcome.ALLOW,
                        f"ArmorIQ allowed {tool} using approved delegation {did}.",
                        "armoriq_delegation_consumed",
                    ),
                    raw=raw,
                    extra={"approved_delegation_id": did, "recheck_hold_ignored": True},
                )
        elif c.invariant == "armoriq_delegation_consumed":
            state.approved.pop(key, None)
        return done(c, raw=raw)

    def _session_check(self, state: _RunState, tool: str, args: dict) -> tuple[Any, Classified]:
        """Call ``session.check`` and classify it, also using the recorded HTTP status (fail closed)."""
        self._tls.enforce_status = None
        try:
            raw = state.session.check(tool, args, user_email=state.user_email or None)
        except Exception as exc:  # noqa: BLE001 - fail closed on anything
            msg = redact_text(f"{type(exc).__name__}: {exc}")[:300]
            return None, Classified(
                DecisionSource.ARMORIQ_ENFORCE,
                Outcome.UNAVAILABLE,
                "ArmorIQ enforcement call failed; refused (fail closed). " + msg,
                "enforcement_unavailable",
            )
        status = getattr(self._tls, "enforce_status", None)
        if isinstance(status, int) and (status >= 500 or status in (401, 429)):
            return raw, Classified(
                DecisionSource.ARMORIQ_ENFORCE,
                Outcome.UNAVAILABLE,
                f"ArmorIQ enforce returned HTTP {status}; refused (fail closed, not a policy denial)",
                "enforcement_http_error",
            )
        c = classify_enforce_result(raw)
        if isinstance(status, int) and not 200 <= status <= 299 and c.outcome == Outcome.ALLOW:
            return raw, Classified(
                DecisionSource.ARMORIQ_ENFORCE,
                Outcome.UNAVAILABLE,
                f"ArmorIQ enforce returned HTTP {status} with an allow result; "
                "refused (fail closed, not a policy allow)",
                "enforcement_http_error",
            )
        return raw, c

    # -- approval -----------------------------------------------------------

    def await_sponsor_approval(
        self, run_id: str, delegation_id: str, timeout_s: float, cancel: threading.Event | None = None
    ) -> ApprovalResult:
        """Poll the delegation status ourselves (cancel-aware).

        Deliberately NOT ``session.await_approval``: on approval the SDK marks the delegation executed,
        so the re-check would open a NEW hold. Here the delegation stays approved; the re-check's
        ``session.check`` then reaches the SDK reuse path (``Allowed by approved delegation``), which
        marks it executed exactly once. The gateway never calls ``mark_delegation_executed``.
        """
        state = self._state(run_id)
        if state is None or state.session is None or self._force_unavailable:
            return "timeout"
        interval = min(5.0, max(0.5, timeout_s / 20.0))
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            if cancel is not None and cancel.is_set():
                return "timeout"
            try:
                status = self.client.get_delegation_status(delegation_id)
            except Exception as exc:  # noqa: BLE001
                code = getattr(exc, "status_code", None)
                if code is not None and code not in (429, 502, 503, 504):
                    log.warning("ArmorIQ delegation status failed (HTTP %s); treating as timeout", code)
                    return "timeout"
                log.warning("ArmorIQ delegation status transient failure: %s", redact_text(str(exc)))
                status = "pending"
            if status == "approved":
                key = state.holds.get(delegation_id)
                if key:
                    state.approved[key] = delegation_id
                return "approved"
            if status == "rejected":
                return "rejected"
            if status in ("expired", "none"):
                return "timeout"
            if time.monotonic() >= deadline:
                return "timeout"
            wait = min(interval, max(0.0, deadline - time.monotonic()))
            if cancel is not None:
                cancel.wait(wait)
            else:
                time.sleep(wait)

    # -- report -------------------------------------------------------------

    def report(
        self, run_id: str, proposal_id: str, tool: str, args: dict, result_summary: dict, status: str
    ) -> None:
        """Best-effort audit report. ``delivered`` means the audit POST returned HTTP < 400."""
        self._tls.audit_status = None
        self._tls.audit_id = None
        state = self._state(run_id)
        payload = _report_payload(tool, args, result_summary, status)
        if state is None or state.session is None:
            oid = _outbox_insert(run_id, proposal_id, payload, "failed", "no ArmorIQ session for this run")
            self._emit_delivery(run_id, proposal_id, tool, "failed", "no ArmorIQ session for this run")
            return
        oid = _outbox_insert(run_id, proposal_id, payload, "pending", None)
        try:
            from armoriq_sdk.session import ReportOptions

            sdk_status = "success" if status == "success" else "failed"
            state.session.report(tool, args, result_summary, ReportOptions(status=sdk_status))
            http_status = getattr(self._tls, "audit_status", None)
            if http_status is None:
                delivery, err = "failed", "audit request did not complete (the SDK swallows transport errors)"
            elif http_status >= 400:
                delivery, err = "failed", f"audit endpoint returned HTTP {http_status}"
            else:
                delivery, err = "delivered", None
        except Exception as exc:  # noqa: BLE001
            delivery, err = "failed", redact_text(f"{type(exc).__name__}: {exc}")[:300]
        _outbox_finish(oid, delivery, err)
        audit_report_id = (
            _validated_audit_id(getattr(self._tls, "audit_id", None))
            if delivery == "delivered" and getattr(self._tls, "audit_status", None) == 200
            else None
        )
        self._emit_delivery(run_id, proposal_id, tool, delivery, err, audit_report_id=audit_report_id)

    @staticmethod
    def _emit_delivery(
        run_id: str,
        proposal_id: str | None,
        tool: str,
        status: str,
        error: str | None,
        *,
        audit_report_id: str | None = None,
    ) -> None:
        try:
            data = {"status": status, "error": error, "tool": tool}
            if status == "delivered" and audit_report_id:
                data["audit_report_id"] = audit_report_id
                data["audit_report_id_source"] = "armoriq.audit_response.audit_id"
            events.emit(
                run_id,
                "telemetry.delivery",
                Actor.SYSTEM,
                f"ArmorIQ audit report {status}",
                f"Report for {tool} {'was accepted by the ArmorIQ audit endpoint' if status == 'delivered' else 'was not delivered'}."
                + (f" ({error})" if error else ""),
                proposal_id=proposal_id,
                data=data,
            )
        except Exception:  # pragma: no cover - telemetry must never break a run
            log.exception("could not emit telemetry.delivery")

    # -- boundary probe -------------------------------------------------------

    def _mint_wider(
        self, tools: list[str], goal: str, email: str, llm: str, validity: int
    ) -> tuple[Any, Any, float]:
        """Throwaway session + plan over ``tools``. Returns (session, token, issuance_latency_ms)."""
        from armoriq_sdk.session import SessionOptions

        if self._force_unavailable:
            raise ConnectionError("enforcement forced unavailable")
        t0 = time.perf_counter()
        session = None
        try:
            client = self.client
            with self._bind_lock:
                session = client.for_user(email).start_session(
                    SessionOptions(
                        mode=self._settings.armoriq_session_mode,
                        default_mcp_name=self._settings.armoriq_mcp_name,
                        validity_seconds=validity,
                        llm=llm,
                    )
                )
                client.user_email_override = email
                token = session.start_plan([{"name": n, "args": {}} for n in tools], goal=goal)
        except Exception:
            if session is not None:
                _safe_close(session)
            raise
        return session, token, (time.perf_counter() - t0) * 1000

    def _backend_decision(
        self,
        run_id: str,
        tool: str,
        raw: Any,
        c: Classified,
        *,
        wider_binding: PlanBinding,
        issuance_ms: float,
        check_ms: float,
        proposal_id: str | None = None,
        shadow: bool = False,
        extra_evidence: dict | None = None,
        reason: str | None = None,
    ) -> Decision:
        matched = getattr(raw, "matched_policy", None)
        if c.outcome == Outcome.BLOCK:
            invariant = "org_policy_allowlist"
            default = (
                f"ArmorIQ signed the wider plan, but its org policy refused {tool} at enforcement: "
                f"{c.reason or ORG_ALLOWLIST_REASON}"
            )
        elif c.outcome == Outcome.ALLOW:
            invariant = "remint_wider_enforce_allowed"
            default = f"ArmorIQ signed the wider plan and its enforcement allowed {tool}: {c.reason}"
        else:
            invariant = c.invariant
            default = f"ArmorIQ enforcement answered {c.outcome.value} for {tool}: {c.reason}"
        return make_decision(
            run_id,
            DecisionSource.ARMORIQ_ENFORCE,
            c.outcome,
            reason or default,
            proposal_id=proposal_id,
            invariant=invariant,
            decisive=not shadow,
            shadow=shadow,
            latency_ms=check_ms,
            sponsor=self._sponsor(
                _RunState(binding=wider_binding),
                raw_action=getattr(raw, "action", None),
                matched_policy=matched,
                sanitized_response=redact_secrets(
                    {
                        "issued": True,
                        "issuance_latency_ms": round(issuance_ms, 1),
                        "check": {
                            "action": getattr(raw, "action", None),
                            "reason": c.reason,
                            "matched_policy": matched,
                            "latency_ms": round(check_ms, 1),
                        },
                    }
                ),
            ),
            evidence={"tool": tool, "wider_plan_issued": True, **(extra_evidence or {})},
        )

    def probe_wider_plan(
        self, run_id: str, grant: TaskGrant, extra_tools: list[str], user_email: str
    ) -> Decision:
        """Ask ArmorIQ to sign a plan that ALSO contains ``extra_tools``, then check them (boundary probe).

        LIVE-OBSERVED: the wider plan is ISSUED (no denied tools at issuance); the org allowlist then blocks
        the extra tool at ``check`` (``tool_not_in_allowlist``, source armoriq.backend.enforce). The wider
        token is discarded and never used for effects. BLOCK at issuance (PolicyBlockedException) is also
        handled. ALLOW is returned only when both issuance and enforcement allow (a genuine finding).
        """
        t0 = time.perf_counter()
        email = self._email(user_email)
        tools = list(grant.allowed_tools) + [t for t in extra_tools if t not in grant.allowed_tools]
        evidence = {"extra_tools": list(extra_tools), "plan_tools": tools}
        try:
            session, token, issuance_ms = self._mint_wider(
                tools, "boundary probe: " + grant.purpose, email, "rewindsafe-boundary-probe", 120
            )
        except Exception as exc:  # noqa: BLE001
            latency = (time.perf_counter() - t0) * 1000
            if type(exc).__name__ == "PolicyBlockedException":
                reason = redact_text(str(getattr(exc, "reason", "") or "Blocked by policy"))[:400]
                meta = getattr(exc, "metadata", None) or {}
                return make_decision(
                    run_id,
                    DecisionSource.ARMORIQ_TOKEN_ISSUANCE,
                    Outcome.BLOCK,
                    f"ArmorIQ refused to sign a wider plan including {', '.join(extra_tools)}: {reason}",
                    invariant="remint_wider_refused",
                    decisive=True,
                    latency_ms=latency,
                    sponsor=self._sponsor(
                        None,
                        sanitized_response=redact_secrets(
                            {
                                "denied_tools": meta.get("denied_tools"),
                                "denied_reasons": meta.get("denied_reasons"),
                                "default_enforcement_action": meta.get("default_enforcement_action"),
                            }
                        ),
                    ),
                    evidence={**evidence, "wider_plan_blocked_at": "issuance"},
                )
            msg = redact_text(f"{type(exc).__name__}: {exc}")[:300]
            return make_decision(
                run_id,
                DecisionSource.ARMORIQ_TOKEN_ISSUANCE,
                Outcome.UNAVAILABLE,
                "ArmorIQ could not be asked to sign a wider plan (fail closed). " + msg,
                invariant="enforcement_unavailable",
                decisive=True,
                latency_ms=latency,
                sponsor=self._sponsor(None, sanitized_response={"error": msg}),
                evidence=evidence,
            )
        wider_binding = PlanBinding(
            mode="live",
            simulated=False,
            plan_id=getattr(token, "plan_id", None),
            plan_hash=getattr(token, "plan_hash", None),
            token_id=getattr(token, "token_id", None),
            steps=tools,
            latency_ms=issuance_ms,
        )
        probe_state = _RunState(session=session, user_email=email, binding=wider_binding)
        decision: Decision | None = None
        try:
            for tool in extra_tools:
                t1 = time.perf_counter()
                raw, c = self._session_check(
                    probe_state,
                    tool,
                    {"tenant_id": grant.tenant_id, "grant_id": "AG-77", "reason": "boundary probe"},
                )
                check_ms = (time.perf_counter() - t1) * 1000
                if raw is None or c.outcome == Outcome.UNAVAILABLE:
                    decision = make_decision(
                        run_id,
                        DecisionSource.ARMORIQ_ENFORCE,
                        Outcome.UNAVAILABLE,
                        f"ArmorIQ signed the wider plan but enforcement for {tool} could not be reached; "
                        f"refused (fail closed). {c.reason}",
                        invariant="enforcement_unavailable",
                        decisive=True,
                        latency_ms=check_ms,
                        sponsor=self._sponsor(
                            _RunState(binding=wider_binding), sanitized_response={"issued": True}
                        ),
                        evidence=evidence,
                    )
                    break
                d = self._backend_decision(
                    run_id,
                    tool,
                    raw,
                    c,
                    wider_binding=wider_binding,
                    issuance_ms=issuance_ms,
                    check_ms=check_ms,
                    extra_evidence={
                        **evidence,
                        "wider_plan_blocked_at": "enforce" if c.outcome == Outcome.BLOCK else None,
                    },
                )
                st = self._state(run_id)
                if st is not None and c.outcome == Outcome.BLOCK:
                    st.wider[tool] = d  # cached per run: org-allowlist evidence for the shadow view
                if decision is None or (c.outcome != Outcome.ALLOW and decision.outcome == Outcome.ALLOW):
                    decision = d
                if c.outcome != Outcome.ALLOW:
                    break
        finally:
            _safe_close(session)
        if decision is None:  # no extra tools requested: nothing wider than the grant
            decision = make_decision(
                run_id,
                DecisionSource.ARMORIQ_TOKEN_ISSUANCE,
                Outcome.ALLOW,
                "ArmorIQ issued the plan; no extra tools were requested.",
                invariant="remint_wider_issued",
                latency_ms=issuance_ms,
                sponsor=self._sponsor(_RunState(binding=wider_binding)),
                evidence=evidence,
            )
        return decision

    def shadow_backend_check(
        self, run_id: str, proposal_id: str | None, tool: str, canonical_args: dict
    ) -> Decision | None:
        """Attribution only: would ArmorIQ's BACKEND org policy also have blocked ``tool``?

        Reuses the org-allowlist evidence from ``probe_wider_plan`` when the run has it; otherwise lazily
        mints ONE throwaway 'attacker-view' plan (grant tools + ``tool``) per run and checks the tool on it.
        The token is never used for effects. Returns a shadow, non-decisive Decision, or None on any failure.
        """
        state = self._state(run_id)
        if state is None or state.session is None or self._force_unavailable:
            return None
        cached = state.wider.get(tool)
        try:
            if cached is not None:
                return make_decision(
                    run_id,
                    DecisionSource.ARMORIQ_ENFORCE,
                    cached.outcome,
                    cached.reason,
                    proposal_id=proposal_id,
                    invariant=cached.invariant,
                    shadow=True,
                    latency_ms=cached.latency_ms,
                    sponsor=cached.sponsor,
                    evidence={**cached.evidence, "purpose": "attribution only; reused boundary-probe evidence"},
                )
            with state.shadow_lock:
                if state.shadow_session is None:
                    steps = list(state.binding.steps) if state.binding else []
                    tools = steps + ([tool] if tool not in steps else [])
                    sess, token, ms = self._mint_wider(
                        tools, "shadow attribution probe", state.user_email, "rewindsafe-shadow-probe", 300
                    )
                    state.shadow_session = sess
                    state.shadow_binding = PlanBinding(
                        mode="live",
                        simulated=False,
                        plan_id=getattr(token, "plan_id", None),
                        plan_hash=getattr(token, "plan_hash", None),
                        token_id=getattr(token, "token_id", None),
                        steps=tools,
                        latency_ms=ms,
                    )
            shadow_state = _RunState(
                session=state.shadow_session, user_email=state.user_email, binding=state.shadow_binding
            )
            t1 = time.perf_counter()
            raw, c = self._session_check(shadow_state, tool, canonical_args)
            check_ms = (time.perf_counter() - t1) * 1000
            if raw is None or c.outcome == Outcome.UNAVAILABLE:
                return None
            sb = state.shadow_binding
            assert sb is not None
            if c.outcome == Outcome.BLOCK:
                text = f"ArmorIQ org policy would also have blocked {tool} ({c.reason or ORG_ALLOWLIST_REASON})"
            else:
                text = (
                    f"ArmorIQ backend enforcement answered {c.outcome.value} for {tool} "
                    f"on the attacker-view plan: {c.reason}"
                )
            return self._backend_decision(
                run_id,
                tool,
                raw,
                c,
                wider_binding=sb,
                issuance_ms=sb.latency_ms or 0.0,
                check_ms=check_ms,
                proposal_id=proposal_id,
                shadow=True,
                reason=text,
                extra_evidence={
                    "shadow_plan_id": sb.plan_id,
                    "shadow_plan_hash": sb.plan_hash,
                    "purpose": "attribution only; token never used for effects",
                    **_args_evidence(tool, canonical_args),
                },
            )
        except Exception as exc:  # noqa: BLE001 - attribution must never break a run
            log.warning("shadow backend check failed: %s", redact_text(str(exc)))
            return None

    # -- lifecycle ----------------------------------------------------------

    def record_generation(
        self,
        run_id: str,
        model: str,
        input_tokens: float,
        output_tokens: float,
        finish_reason: str | None = None,
    ) -> None:
        state = self._state(run_id)
        if state is None or state.session is None:
            return
        try:
            state.session.record_generation(
                model=model,
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
                finish_reason=finish_reason,
            )
        except Exception:
            log.debug("record_generation failed", exc_info=True)

    def _complete_plan(self, plan_id: str | None, outcome: str | None) -> dict:
        data: dict[str, Any] = {"plan_id": plan_id, "outcome": outcome, "completed": False}
        if not plan_id:
            data["reason"] = "no plan was bound"
            return data
        if outcome is not None and outcome not in COMPLETABLE_OUTCOMES:
            data["reason"] = f"run ended {outcome}; the plan is deliberately left open"
            return data
        self._tls.plan_status = None
        try:
            self.client.complete_plan(plan_id)
        except Exception as exc:  # noqa: BLE001 - best effort
            data["reason"] = redact_text(f"{type(exc).__name__}: {exc}")[:200]
            return data
        status = getattr(self._tls, "plan_status", None)
        data["http_status"] = status
        data["completed"] = True if status is None else status < 400
        if status is None:
            data["reason"] = "completion HTTP status not observed (the SDK swallows errors)"
        return data

    def close_run(self, run_id: str, outcome: str | None = None) -> None:
        with self._runs_lock:
            state = self._runs.pop(run_id, None)
        if state is None:
            return
        plan_id = state.binding.plan_id if state.binding else None
        if state.session is not None:
            data = self._complete_plan(plan_id, outcome)
            try:
                state.session.flush_observability()
            except Exception:  # noqa: BLE001
                pass
            data["observability_http_status"] = self._obs_status
            data["observability_session_id"] = state.observability_session_id
            _emit_plan_lifecycle(run_id, data, simulated=False)
            _safe_close(state.session)
        if state.shadow_session is not None:
            _safe_close(state.shadow_session)

    # -- readiness ----------------------------------------------------------

    def readiness(self) -> dict:
        """Cached live probe result. Starts a background probe (at most once per 10 min); never raises."""
        try:
            if not self._settings.armoriq_configured:
                return {**self._readiness, "state": "unverified", "detail": "ARMORIQ_API_KEY is not set."}
            with self._readiness_lock:
                running = self._readiness_thread is not None and self._readiness_thread.is_alive()
                last = self._readiness_attempt_at
                if not running and (last is None or time.monotonic() - last > READINESS_TTL_S):
                    self._readiness_attempt_at = time.monotonic()
                    self._readiness_thread = threading.Thread(
                        target=self.run_readiness_probe, name="armoriq-readiness", daemon=True
                    )
                    self._readiness_thread.start()
                return dict(self._readiness)
        except Exception as exc:  # noqa: BLE001
            return {**self._readiness, "state": "failed", "detail": f"readiness unavailable: {type(exc).__name__}"}

    def run_readiness_probe(self) -> dict:
        """Synchronous probe: bind a 1-tool plan and run 1 check. Updates and returns the cached result."""
        rid = "rs-readiness-" + new_id("p")[-8:]
        result: dict[str, Any] = {
            "state": "failed",
            "checked_at": utcnow().isoformat(),
            "detail": "",
            "matched_policy": None,
            "plan_latency_ms": None,
            "check_latency_ms": None,
        }
        plan_id = None
        try:
            email = self._email("")
            if not email:
                result["detail"] = "ARMORIQ_USER_EMAIL is not set; cannot mint a plan."
            else:
                probe_grant = SimpleNamespace(purpose="RewindSafe readiness probe")
                binding, bd = self.bind_plan_with_decision(
                    rid,
                    probe_grant,  # type: ignore[arg-type]
                    [{"name": "inspect_snapshot", "args": {}}],
                    email,
                    llm="rewindsafe-readiness",
                )
                plan_id = binding.plan_id
                result["plan_latency_ms"] = round(binding.latency_ms or bd.latency_ms or 0.0, 1)
                if binding.error:
                    result["detail"] = redact_text(binding.error)[:300]
                else:
                    d = self.check(rid, "readiness", "inspect_snapshot", {})
                    result["check_latency_ms"] = round(d.latency_ms or 0.0, 1)
                    result["matched_policy"] = d.sponsor.matched_policy if d.sponsor else None
                    if d.outcome == Outcome.ALLOW:
                        result["state"] = "verified"
                        result["detail"] = "ArmorIQ signed a plan and allowed an in-plan read."
                    else:
                        result["detail"] = f"ArmorIQ answered {d.outcome.value}: {d.reason}"[:300]
        except Exception as exc:  # noqa: BLE001
            result["detail"] = redact_text(f"{type(exc).__name__}: {exc}")[:300]
        finally:
            with self._runs_lock:
                st = self._runs.pop(rid, None)
            if st is not None and st.session is not None:
                if plan_id and result["state"] == "verified":
                    try:
                        self.client.complete_plan(plan_id)
                    except Exception:  # noqa: BLE001
                        pass
                _safe_close(st.session)
        with self._readiness_lock:
            self._readiness = result
        return dict(result)


COMPLETABLE_OUTCOMES = frozenset({"succeeded", "partially_succeeded", "blocked"})


def _emit_plan_lifecycle(run_id: str, data: dict, *, simulated: bool) -> None:
    done = bool(data.get("completed"))
    try:
        events.emit(
            run_id,
            "telemetry.delivery",
            Actor.SYSTEM if simulated else Actor.ARMORIQ,
            "ArmorIQ plan marked completed" if done else "ArmorIQ plan left open",
            "(simulated) nothing was sent to ArmorIQ" if simulated else (data.get("reason") or ""),
            data={"kind": "plan.completed" if done else "plan.left_open", "simulated": simulated, **data},
        )
    except Exception:  # pragma: no cover - telemetry must never break a run
        log.debug("could not emit plan lifecycle event", exc_info=True)


def _safe_close(session: Any) -> None:
    try:
        session.close()
    except Exception:  # pragma: no cover
        pass


# ─── offline simulation ───────────────────────────────────────────────────


@dataclass
class _SimRun:
    plan_tools: set[str] = field(default_factory=set)
    binding: PlanBinding | None = None
    holds: dict[str, str] = field(default_factory=dict)  # delegation_id -> action digest
    approved: set[str] = field(default_factory=set)  # action digests with an approved simulated delegation


class OfflineSimulatedGateway:
    """Deterministic SIMULATION of ArmorIQ with the same semantics (never sponsor evidence)."""

    mode: Literal["live", "offline"] = "offline"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._runs: dict[str, _SimRun] = {}
        self._lock = threading.Lock()
        self._force_unavailable = False

    def force_unavailable(self, flag: bool) -> None:
        self._force_unavailable = bool(flag)

    def describe(self) -> dict:
        return {
            "mode": "offline",
            "simulated": True,
            "sdk_version": sdk_version(),
            "session_mode": "simulated",
            "env": "offline-simulation",
            "configured": self._settings.armoriq_configured,
            "user_email": self._settings.armoriq_user_email,
        }

    def _sponsor(self, run: _SimRun | None, **kw: Any) -> SponsorDetail:
        b = run.binding if run else None
        return SponsorDetail(
            mode="offline",
            session_mode="simulated",
            sdk_version=sdk_version(),
            plan_id=b.plan_id if b else None,
            plan_hash=b.plan_hash if b else None,
            token_id=b.token_id if b else None,
            **kw,
        )

    def hold_threshold(self) -> Decimal | None:
        """Simulated HOLD threshold, or None (the default) = no HOLD, matching the live workspace today."""
        raw = getattr(self._settings, "sim_hold_threshold", None) or os.environ.get(SIM_HOLD_ENV, "")
        return _as_decimal(str(raw).strip()) if str(raw or "").strip() else None

    def bind_plan(
        self,
        run_id: str,
        grant: TaskGrant,
        tool_calls: list[dict],
        user_email: str,
        *,
        llm: str = "rewindsafe-agent",
    ) -> PlanBinding:
        steps = [str(tc["name"]) for tc in tool_calls]
        now = utcnow()
        binding = PlanBinding(
            mode="offline",
            simulated=True,
            plan_id=new_id("sim-plan"),
            plan_hash=digest({"goal": grant.purpose, "steps": tool_calls}),
            token_id=new_id("sim-token"),
            issued_at=now,
            expires_at=now + timedelta(seconds=PLAN_VALIDITY_SECONDS),
            steps=steps,
            sdk_version=sdk_version(),
            session_mode="simulated",
            latency_ms=0.0,
            matched_policies=["armoriq.yaml allowlist (simulated)"],
        )
        with self._lock:
            self._runs[run_id] = _SimRun(plan_tools=set(steps), binding=binding)
        return binding

    def check(self, run_id: str, proposal_id: str, tool: str, canonical_args: dict) -> Decision:
        t0 = time.perf_counter()
        with self._lock:
            run = self._runs.get(run_id)
        evidence = {
            **_args_evidence(tool, canonical_args),
            "simulation": "Offline mode: this is a SIMULATED ArmorIQ decision, not sponsor enforcement evidence.",
        }

        def out(
            outcome: Outcome,
            reason: str,
            invariant: str | None,
            delegation_id: str | None = None,
            raw: str = "",
        ) -> Decision:
            return make_decision(
                run_id,
                DecisionSource.ARMORIQ_SIMULATED,
                outcome,
                reason,
                proposal_id=proposal_id,
                invariant=invariant,
                simulated=True,
                latency_ms=(time.perf_counter() - t0) * 1000,
                sponsor=self._sponsor(
                    run,
                    raw_action=raw or None,
                    delegation_id=delegation_id,
                    matched_policy="rewindsafe-simulated-policy" if raw else None,
                    sanitized_response={"simulated": True, "action": raw or None, "reason": reason},
                ),
                evidence=evidence,
            )

        if self._force_unavailable:
            return out(
                Outcome.UNAVAILABLE,
                "Simulated ArmorIQ outage; refused (fail closed).",
                "enforcement_unavailable",
            )
        if run is None:
            return out(
                Outcome.UNAVAILABLE,
                "No simulated plan is bound for this run; refused (fail closed).",
                "no_signed_plan",
            )
        if tool not in run.plan_tools:
            return out(
                Outcome.BLOCK,
                f"tool-not-in-plan: '{tool}' was not declared in the (simulated) signed plan",
                "tool_not_in_signed_plan",
                raw="block",
            )
        if tool in OFFLINE_DENIED_TOOLS:
            return out(
                Outcome.BLOCK,
                SIM_ALLOWLIST_REASON,
                "org_policy_allowlist",
                raw="block",
            )
        if tool == OFFLINE_HOLD_TOOL:
            amount = _as_decimal(canonical_args.get("amount"))
            if amount is None:
                return out(
                    Outcome.BLOCK,
                    f"No (simulated) policy statement allows '{tool}' without an amount; default deny.",
                    "armoriq_policy",
                    raw="block",
                )
            threshold = self.hold_threshold()
            if threshold is not None and amount > threshold:
                key = digest({"tool": tool, "args": canonical_args})
                with self._lock:
                    if key in run.approved:
                        return out(
                            Outcome.ALLOW, "Allowed by an approved simulated delegation.", None, raw="allow"
                        )
                    existing = next((d for d, k in run.holds.items() if k == key), None)
                    delegation_id = existing or new_id("sim-deleg")
                    run.holds[delegation_id] = key
                return out(
                    Outcome.HOLD,
                    f"Amount {amount} USD requires approval (simulated threshold: {threshold}; "
                    "proposed policy.rewindsafe.json, NOT active in the live workspace).",
                    "armoriq_hold",
                    delegation_id=delegation_id,
                    raw="hold",
                )
        return out(Outcome.ALLOW, "Allowed by the (simulated) org policy.", None, raw="allow")

    def await_sponsor_approval(
        self, run_id: str, delegation_id: str, timeout_s: float, cancel: threading.Event | None = None
    ) -> ApprovalResult:
        """Simulation: 'approved' exactly when the RewindSafe approval record is approved."""
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            with db.connection() as conn:
                row = conn.execute(
                    "SELECT status FROM runtime.approvals WHERE body->>'sponsor_delegation_id' = %s "
                    "ORDER BY requested_at DESC LIMIT 1",
                    (delegation_id,),
                ).fetchone()
            status = row["status"] if row else "pending"
            if status == "approved":
                with self._lock:
                    run = self._runs.get(run_id)
                    if run and delegation_id in run.holds:
                        run.approved.add(run.holds[delegation_id])
                return "approved"
            if status == "rejected":
                return "rejected"
            if status in ("timed_out", "expired", "cancelled"):
                return "timeout"
            if time.monotonic() >= deadline or (cancel is not None and cancel.is_set()):
                return "timeout"
            (cancel.wait(0.5) if cancel is not None else time.sleep(0.5))

    def report(
        self, run_id: str, proposal_id: str, tool: str, args: dict, result_summary: dict, status: str
    ) -> None:
        payload = _report_payload(tool, args, result_summary, status)
        _outbox_insert(run_id, proposal_id, payload, "skipped", "offline mode: nothing was sent to ArmorIQ")
        LiveArmorIQGateway._emit_delivery(
            run_id, proposal_id, tool, "skipped", "offline mode: nothing was sent to ArmorIQ"
        )

    def probe_wider_plan(
        self, run_id: str, grant: TaskGrant, extra_tools: list[str], user_email: str
    ) -> Decision:
        """Mirrors the live-observed behavior: the wider plan is issued, then its check is blocked."""
        return make_decision(
            run_id,
            DecisionSource.ARMORIQ_SIMULATED,
            Outcome.BLOCK,
            f"SIMULATED: the wider plan including {', '.join(extra_tools)} was issued, then blocked at enforcement: "
            f"{SIM_ALLOWLIST_REASON} (mirrors live behavior observed 2026-10-07).",
            invariant="org_policy_allowlist",
            decisive=True,
            simulated=True,
            sponsor=self._sponsor(
                None,
                raw_action="block",
                sanitized_response={"simulated": True, "issued": True, "check": {"action": "block", "reason": SIM_ALLOWLIST_REASON}},
            ),
            evidence={
                "extra_tools": list(extra_tools),
                "wider_plan_issued": True,
                "wider_plan_blocked_at": "enforce",
                "simulation": "Offline mode: this is a SIMULATED ArmorIQ decision, not sponsor enforcement evidence.",
            },
        )

    def shadow_backend_check(
        self, run_id: str, proposal_id: str | None, tool: str, canonical_args: dict
    ) -> Decision | None:
        if tool not in OFFLINE_DENIED_TOOLS:
            return None
        return make_decision(
            run_id,
            DecisionSource.ARMORIQ_SIMULATED,
            Outcome.BLOCK,
            f"SIMULATED: ArmorIQ org policy would also have blocked {tool} ({SIM_ALLOWLIST_REASON})",
            proposal_id=proposal_id,
            invariant="org_policy_allowlist",
            shadow=True,
            simulated=True,
            sponsor=self._sponsor(None, raw_action="block", sanitized_response={"simulated": True}),
            evidence={**_args_evidence(tool, canonical_args), "purpose": "attribution only (simulation)"},
        )

    def record_generation(
        self,
        run_id: str,
        model: str,
        input_tokens: float,
        output_tokens: float,
        finish_reason: str | None = None,
    ) -> None:
        return None

    def readiness(self) -> dict:
        return {
            "state": "simulated",
            "checked_at": utcnow().isoformat(),
            "detail": "Offline mode: ArmorIQ is simulated, nothing is sent to the sponsor.",
            "matched_policy": None,
            "plan_latency_ms": None,
            "check_latency_ms": None,
        }

    def close_run(self, run_id: str, outcome: str | None = None) -> None:
        with self._lock:
            run = self._runs.pop(run_id, None)
        if run is not None and run.binding is not None:
            data = {
                "plan_id": run.binding.plan_id,
                "outcome": outcome,
                "completed": outcome is None or outcome in COMPLETABLE_OUTCOMES,
            }
            if not data["completed"]:
                data["reason"] = f"run ended {outcome}; the plan is deliberately left open"
            _emit_plan_lifecycle(run_id, data, simulated=True)


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


# ─── singleton ────────────────────────────────────────────────────────────

_gateway: EnforcementGateway | None = None
_gateway_lock = threading.Lock()


def get_gateway() -> EnforcementGateway:
    """Process singleton chosen by ``settings.effective_enforcement()``."""
    global _gateway
    with _gateway_lock:
        if _gateway is None:
            settings = get_settings()
            settings.validate_startup()
            _gateway = (
                LiveArmorIQGateway(settings)
                if settings.effective_enforcement() == "live"
                else OfflineSimulatedGateway(settings)
            )
        return _gateway


def set_gateway_for_tests(g: EnforcementGateway | None) -> None:
    """Install ``g`` as the singleton (``None`` clears it so the next ``get_gateway`` rebuilds)."""
    global _gateway
    with _gateway_lock:
        _gateway = g


__all__ = [
    "READINESS_TTL_S",
    "ApprovalResult",
    "EnforcementGateway",
    "LiveArmorIQGateway",
    "OfflineSimulatedGateway",
    "classify_enforce_result",
    "get_gateway",
    "sdk_version",
    "set_gateway_for_tests",
]
