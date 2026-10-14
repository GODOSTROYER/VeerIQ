"""Gateway hardening: ArmorIQ call timeout, non-2xx enforce never ALLOW, policy YAML vs simulator/plan drift.

Offline only: the SDK client is a fake or a real client with validation skipped and an httpx MockTransport.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import httpx
import pytest

from rewindsafe.config import REPO_ROOT, Settings
from rewindsafe.contracts import DecisionSource, Outcome
from rewindsafe.runtime import armoriq_gateway
from rewindsafe.runtime.armoriq_gateway import LiveArmorIQGateway

from .test_w1_live_gateway import FakeSession, er, gateway_with

POLICY_PATH = REPO_ROOT / "armoriq" / "armoriq.yaml"
POLICY_PREFIX = "rewindsafe-recovery."


def _check_with_enforce_http_status(result, status: int):
    """Run ``check`` where the enforce call returns ``result`` and the httpx hook recorded ``status``."""
    gw = None

    class S(FakeSession):
        def check(self, tool, args, user_email=None):
            gw._tls.enforce_status = status  # what the httpx response hook records
            return result

    gw = gateway_with(S())
    return gw.check("run_1", "p", "inspect_snapshot", {})


# ── gap 1: the ArmorIQ call timeout ─────────────────────────────────────────


def test_sdk_client_constructor_accepts_a_timeout():
    from armoriq_sdk import ArmorIQClient

    assert "timeout" in inspect.signature(ArmorIQClient.__init__).parameters


def test_default_client_factory_passes_the_configured_timeout(monkeypatch):
    import armoriq_sdk

    built: list[dict] = []

    class FakeArmorIQClient:
        def __init__(self, **kwargs):
            built.append(kwargs)
            self.http_client = SimpleNamespace(event_hooks={"response": []})

    monkeypatch.setattr(armoriq_sdk, "ArmorIQClient", FakeArmorIQClient)
    monkeypatch.setenv("ARMORIQ_ENV", "production")
    # Init kwargs must use the env alias: the field-name form is ignored for this field.
    gw = LiveArmorIQGateway(
        Settings(_env_file=None, armoriq_api_key="ak_test_FAKE", REWINDSAFE_ARMORIQ_TIMEOUT_S=7.5),
    )
    client = gw.client
    assert built == [{"api_key": "ak_test_FAKE", "use_production": True, "timeout": 7.5}]
    assert len(client.http_client.event_hooks["response"]) == 1  # the status hook is still installed


def test_session_check_timeout_is_unavailable_never_allow():
    request = httpx.Request("POST", "https://iap.example/iap/sdk/enforce")
    d = gateway_with(FakeSession(exc=httpx.ReadTimeout("timed out", request=request))).check(
        "run_1", "p", "inspect_snapshot", {}
    )
    assert d.source == DecisionSource.ARMORIQ_ENFORCE
    assert d.outcome == Outcome.UNAVAILABLE and d.invariant == "enforcement_unavailable"


def test_real_sdk_enforce_timeout_reaches_the_gateway_as_unavailable():
    """The SDK swallows a transport timeout inside enforce and returns ``enforce-unavailable`` (no raise).

    Uses the installed SDK's own session class with an httpx MockTransport that times out. No network.
    """
    from armoriq_sdk import ArmorIQClient
    from armoriq_sdk.observability.recorder import ObservabilityConfig
    from armoriq_sdk.session import ArmorIQSession, SessionOptions

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = ArmorIQClient(
        api_key="ak_test_FAKE",
        use_production=True,
        timeout=7.5,
        _skip_api_key_validation=True,
    )
    client.http_client = httpx.Client(transport=httpx.MockTransport(timeout_handler))
    sdk_session = ArmorIQSession(
        client,
        SessionOptions(
            mode="sdk",
            default_mcp_name="rewindsafe-recovery",
            observability=ObservabilityConfig(enabled=False),
        ),
    )
    sdk_session._current_token = SimpleNamespace(raw_token="x", policy_snapshot=[])
    sdk_session._declared_tools = {"inspect_snapshot"}
    d = gateway_with(sdk_session).check("run_1", "p", "inspect_snapshot", {})
    assert d.outcome == Outcome.UNAVAILABLE and d.invariant == "enforcement_unavailable"


# ── gap 2: a non-2xx enforce response is never ALLOW ────────────────────────


@pytest.mark.parametrize("code", [302, 400, 404, 422])
def test_non_2xx_enforce_with_an_allow_result_is_unavailable(code):
    d = _check_with_enforce_http_status(er("allow", True, "Allowed by policy"), code)
    assert d.outcome == Outcome.UNAVAILABLE and d.invariant == "enforcement_http_error"
    assert f"HTTP {code}" in d.reason


@pytest.mark.parametrize("code", [200, 204])
def test_2xx_enforce_with_an_allow_result_is_allow(code):
    d = _check_with_enforce_http_status(er("allow", True, "Allowed by policy"), code)
    assert d.outcome == Outcome.ALLOW


def test_403_policy_denial_stays_a_block():
    d = _check_with_enforce_http_status(er("block", False, "forbidden by policy", matched="p"), 403)
    assert d.outcome == Outcome.BLOCK and d.invariant == "armoriq_policy"


@pytest.mark.parametrize(
    ("status", "result", "outcome"),
    [
        (403, er("hold", False, "needs approval", delegation_id="d-1"), Outcome.HOLD),
        (404, er("block", False, "no such tool"), Outcome.BLOCK),
    ],
)
def test_4xx_hold_and_block_classifications_are_unchanged(status, result, outcome):
    assert _check_with_enforce_http_status(result, status).outcome == outcome


# ── gap 3: simulator and registered policy must agree ───────────────────────


def test_policy_yaml_matches_the_offline_denied_tools_and_plan_tools():
    yaml = pytest.importorskip("yaml")
    from rewindsafe.workflows.rewindsafe import tools

    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))["policy"]
    allow, deny = list(policy["allow"]), list(policy["deny"])
    assert all(name.startswith(POLICY_PREFIX) for name in allow + deny), "every entry is prefixed"
    allow_tools = [name.removeprefix(POLICY_PREFIX) for name in allow]
    deny_tools = [name.removeprefix(POLICY_PREFIX) for name in deny]
    assert len(set(allow_tools)) == len(allow_tools) and len(set(deny_tools)) == len(deny_tools)
    assert set(deny_tools) == armoriq_gateway.OFFLINE_DENIED_TOOLS
    assert set(allow_tools) == set(tools.PLAN_TOOLS)
