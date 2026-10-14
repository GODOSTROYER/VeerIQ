"""Shared helpers for route handlers: adapter lookup, tenant ownership, error translation."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType

from rewindsafe.api.errors import ApiError, bad_request, conflict, forbidden, not_found
from rewindsafe.contracts import ApprovalStatus, Identity, Run, TaskGrant
from rewindsafe.runtime import adapter as adapter_registry
from rewindsafe.runtime import approvals, grants

WORKFLOW_ID = "rewindsafe.order_repair"


def get_workflow_adapter():
    return adapter_registry.get_adapter(WORKFLOW_ID)


def agent_api() -> ModuleType:
    """The agent module exposing start_run / cancel_run (package or its ``loop`` submodule)."""
    pkg = importlib.import_module("rewindsafe.agent")
    if hasattr(pkg, "start_run") and hasattr(pkg, "cancel_run"):
        return pkg
    return importlib.import_module("rewindsafe.agent.loop")


_APPROVAL_STATUS = {
    "approval_not_found": 404,
    "reviewer_role_required": 403,
    "tenant_mismatch": 403,
    "separation_of_duties": 403,
    "bad_decision": 400,
}


@contextmanager
def translate_domain_errors() -> Iterator[None]:
    """Map runtime-module exceptions onto the API error format.

    Typed errors from ``grants`` / ``approvals`` keep their machine code. The
    builtin fallbacks used by the agent module are PermissionError -> 403,
    LookupError (KeyError) -> 404 and ValueError -> 409 (a state or rule
    violation such as "grant not active"). Anything else propagates and is
    rendered as a generic 500.
    """
    try:
        yield
    except ApiError:
        raise
    except approvals.ApprovalError as exc:
        raise ApiError(_APPROVAL_STATUS.get(exc.code, 409), exc.code, exc.message) from exc
    except grants.GrantNotFound as exc:
        raise ApiError(404, exc.code, str(exc)) from exc
    except grants.GrantPermissionError as exc:
        raise ApiError(403, exc.code, str(exc)) from exc
    except grants.GrantError as exc:
        raise ApiError(409, exc.code, str(exc)) from exc
    except PermissionError as exc:
        raise forbidden(str(exc) or "Not permitted.") from exc
    except LookupError as exc:
        raise not_found(str(exc).strip("'\"") or "Not found.") from exc
    except ValueError as exc:
        raise conflict(str(exc) or "Request conflicts with the current state.") from exc


def load_grant_for(identity: Identity, grant_id: str) -> TaskGrant:
    """Load a grant; other tenants' grants are indistinguishable from missing ones."""
    try:
        grant = grants.load(grant_id)
    except (grants.GrantNotFound, LookupError) as exc:
        raise not_found("Grant not found.") from exc
    if grant is None or grant.tenant_id != identity.tenant_id:
        raise not_found("Grant not found.")
    return grant


def resolve_planner(requested: str | None, scenario_default: str) -> str:
    """``auto`` (or omitted) means "use the scenario's default planner"."""
    if requested in (None, "auto"):
        return scenario_default
    return requested


def require_principal(identity: Identity, grant: TaskGrant) -> None:
    if grant.principal != identity.identity_id:
        raise forbidden("Only the operator who drafted this grant can act on it.", "not_grant_principal")


def load_run_for(identity: Identity, run_id: str) -> Run:
    from rewindsafe.api import queries

    found = queries.get_run_with_tenant(run_id)
    if found is None or found[1] != identity.tenant_id:
        raise not_found("Run not found.")
    return found[0]


def parse_status_filter(status: str | None) -> str | None:
    if not status:
        return None
    if status not in {s.value for s in ApprovalStatus}:
        raise bad_request(f"Unknown approval status '{status}'.")
    return status


def cancel_active_runs(reason: str) -> int:
    """Stop live worker threads before a fixture reset (loop.cancel_all_active, non-blocking-ish).

    Falls back to ``cancel_active_runs`` if that is what the agent module exposes. Returns the number stopped.
    """
    mod = agent_api()
    fn = getattr(mod, "cancel_all_active", None)
    if fn is None:
        loop = importlib.import_module("rewindsafe.agent.loop")
        fn = getattr(loop, "cancel_all_active", None)
    if fn is None:
        return 0
    result = fn(reason, wait_s=2.0)
    return len(result) if isinstance(result, (list, tuple, set)) else int(result or 0)


def active_run_ids() -> list[str]:
    from rewindsafe.contracts import TERMINAL_RUN_STATUSES
    from rewindsafe.runtime import db

    terminal = sorted(s.value if hasattr(s, "value") else s for s in TERMINAL_RUN_STATUSES)
    try:
        with db.connection() as conn:
            rows = conn.execute(
                "SELECT run_id FROM runtime.runs WHERE NOT (status = ANY(%s))", (terminal,)
            ).fetchall()
    except Exception:  # advisory: the reset itself must still proceed
        return []
    return [r["run_id"] for r in rows]


def close_cancelled_runs(run_ids: list[str], outcome: str) -> None:
    """Give runs cancelled underneath a reset a run.finished event so their SSE streams close."""
    from rewindsafe.api import queries
    from rewindsafe.contracts import Actor
    from rewindsafe.runtime import events

    for run_id in run_ids:
        try:
            if queries.finished_seq(run_id) is not None:
                continue
            events.emit(
                run_id, "run.finished", Actor.SYSTEM, f"Run cancelled: {outcome}", outcome,
                data={"status": "cancelled", "outcome_summary": outcome},
            )
        except Exception:  # best effort; the DB row is already terminal
            continue
