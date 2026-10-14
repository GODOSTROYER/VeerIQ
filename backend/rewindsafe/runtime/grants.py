"""Task grants: the human-reviewed authority ceiling for one task (architecture.md 4.7).

``runtime.task_grants.body`` is the authoritative copy of the immutable,
authority-bearing fields. The mutable lifecycle fields (``status``,
``commits_used``, ``expires_at``, ``authorized_*``, ``fixture_generation``) live
in dedicated columns and :func:`load` overlays them onto the body, so a writer
that only updates the columns (e.g. the executor incrementing ``commits_used``)
is always reflected.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from psycopg.types.json import Jsonb

from rewindsafe.contracts import (
    Decision,
    DecisionSource,
    GrantStatus,
    Identity,
    Layer,
    Outcome,
    ScenarioSpec,
    TaskGrant,
)
from rewindsafe.runtime import db
from rewindsafe.runtime.adapter import WorkflowAdapter, make_decision
from rewindsafe.runtime.canonical import digest, new_id, to_jsonable, utcnow

log = logging.getLogger(__name__)

DEFAULT_GRANT_TTL = timedelta(minutes=30)


class GrantError(Exception):
    """Base class; ``code`` is a stable machine-readable reason."""

    code = "grant_error"


class GrantNotFound(GrantError):
    code = "grant_not_found"


class GrantPermissionError(GrantError):
    code = "grant_forbidden"


class GrantStateError(GrantError):
    code = "grant_invalid_state"


# ─── digest ───────────────────────────────────────────────────────────────


def compute_grant_digest(grant: TaskGrant) -> str:
    """Digest over the authority-bearing fields (architecture.md 4.7)."""
    return digest(
        {
            "workflow": grant.workflow,
            "principal": grant.principal,
            "tenant_id": grant.tenant_id,
            "purpose": grant.purpose,
            "allowed_tools": grant.allowed_tools,
            "resources": grant.resources,
            "reviewable": grant.reviewable,
            "fields": grant.fields,
            "prohibited_effects": grant.prohibited_effects,
            "source_constraints": grant.source_constraints,
            "limits": grant.limits,
            "expires_at": grant.expires_at,
            "fixture_generation": grant.fixture_generation,
        }
    )


# ─── persistence ──────────────────────────────────────────────────────────


def current_generation() -> int:
    with db.connection() as conn:
        row = conn.execute("SELECT generation FROM runtime.fixture_state WHERE id = 1").fetchone()
    return int(row["generation"]) if row else 0


def _row_to_grant(row: dict[str, Any]) -> TaskGrant:
    body = dict(row["body"])
    body.update(
        status=row["status"],
        commits_used=row["commits_used"],
        expires_at=row["expires_at"],
        authorized_at=row["authorized_at"],
        authorized_by=row["authorized_by"],
        fixture_generation=row["fixture_generation"],
        grant_digest=row["grant_digest"],
    )
    return TaskGrant.model_validate(body)


def load(grant_id: str) -> TaskGrant:
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM runtime.task_grants WHERE grant_id = %s", (grant_id,)).fetchone()
    if row is None:
        raise GrantNotFound(f"grant {grant_id} not found")
    return _row_to_grant(row)


def create_draft(adapter: WorkflowAdapter, scenario: ScenarioSpec, identity: Identity) -> TaskGrant:
    """Ask the adapter for a DRAFT grant, normalize it, and persist it (``status=draft``).

    The runtime owns ``grant_id``, ``status`` and ``grant_digest``: whatever the adapter put
    there is replaced, so the digest always matches the persisted fields.
    """
    generation = current_generation()
    grant = adapter.build_grant(scenario, identity, generation)
    update: dict[str, Any] = {
        "status": GrantStatus.DRAFT,
        "commits_used": 0,
        "authorized_at": None,
        "authorized_by": None,
        "fixture_generation": generation,
    }
    if not grant.grant_id:
        update["grant_id"] = new_id("grt")
    grant = grant.model_copy(update=update)
    grant = grant.model_copy(update={"grant_digest": compute_grant_digest(grant)})
    _insert(grant)
    return grant


def _insert(grant: TaskGrant) -> None:
    with db.autocommit_connection() as conn:
        conn.execute(
            """
            INSERT INTO runtime.task_grants
              (grant_id, workflow, scenario_id, principal, principal_email, tenant_id, incident_id,
               purpose, body, status, commits_used, max_commits, created_at, expires_at,
               authorized_at, authorized_by, fixture_generation, grant_digest)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                grant.grant_id,
                grant.workflow,
                grant.scenario_id,
                grant.principal,
                grant.principal_email,
                grant.tenant_id,
                grant.incident_id,
                grant.purpose,
                Jsonb(to_jsonable(grant)),
                grant.status.value,
                grant.commits_used,
                grant.limits.max_commits,
                grant.created_at,
                grant.expires_at,
                grant.authorized_at,
                grant.authorized_by,
                grant.fixture_generation,
                grant.grant_digest,
            ),
        )


def authorize(grant_id: str, identity: Identity) -> TaskGrant:
    """Only ``grant.principal`` may authorize; ``draft`` -> ``active`` with a 30-minute expiry."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM runtime.task_grants WHERE grant_id = %s FOR UPDATE", (grant_id,)
        ).fetchone()
        if row is None:
            raise GrantNotFound(f"grant {grant_id} not found")
        grant = _row_to_grant(row)
        if identity.identity_id != grant.principal:
            raise GrantPermissionError(
                f"only the grant principal ({grant.principal}) may authorize this grant"
            )
        if identity.tenant_id != grant.tenant_id:
            raise GrantPermissionError("identity belongs to a different tenant than the grant")
        if grant.status != GrantStatus.DRAFT:
            raise GrantStateError(f"grant is {grant.status.value}; only a draft can be authorized")
        gen = conn.execute("SELECT generation FROM runtime.fixture_state WHERE id = 1").fetchone()
        if gen is None or int(gen["generation"]) != grant.fixture_generation:
            raise GrantStateError(
                "the demo fixture was reset after this draft was created; create a new draft"
            )
        now = utcnow()
        active = grant.model_copy(
            update={
                "status": GrantStatus.ACTIVE,
                "authorized_at": now,
                "authorized_by": identity.identity_id,
                "expires_at": now + DEFAULT_GRANT_TTL,
            }
        )
        active = active.model_copy(update={"grant_digest": compute_grant_digest(active)})
        conn.execute(
            """UPDATE runtime.task_grants
               SET status = 'active', authorized_at = %s, authorized_by = %s, expires_at = %s,
                   grant_digest = %s, body = %s
               WHERE grant_id = %s""",
            (
                active.authorized_at,
                active.authorized_by,
                active.expires_at,
                active.grant_digest,
                Jsonb(to_jsonable(active)),
                grant_id,
            ),
        )
    return active


def revoke(grant_id: str) -> None:
    """Operator revocation: every later dispatch is blocked by ``lifecycle_check``."""
    with db.autocommit_connection() as conn:
        conn.execute("UPDATE runtime.task_grants SET status = 'revoked' WHERE grant_id = %s", (grant_id,))


def close(grant_id: str, reason: str = "run finished") -> TaskGrant:
    """One grant = one run: mark an ACTIVE grant ``exhausted`` once its run is terminal.

    Idempotent: a grant that is not active (draft/expired/revoked/already exhausted) is returned
    unchanged. Mutators were already blocked by the commit budget; this also ends read access.
    """
    with db.transaction() as conn:
        row = conn.execute(
            "UPDATE runtime.task_grants SET status = 'exhausted' WHERE grant_id = %s AND status = 'active' "
            "RETURNING grant_id",
            (grant_id,),
        ).fetchone()
        if row is not None:
            log.info("grant %s closed: %s", grant_id, reason)
    return load(grant_id)


# ─── checks ───────────────────────────────────────────────────────────────


def lifecycle_check(
    grant: TaskGrant,
    fixture_generation: int,
    *,
    run_id: str = "",
    proposal_id: str | None = None,
    tool_is_mutator: bool = False,
) -> Decision | None:
    """BLOCK (source LIFECYCLE) unless the grant can currently be used; ``None`` when OK.

    * not ``active`` (draft/expired/revoked) -> block; ``exhausted`` only blocks mutators so the
      agent can still fetch its receipt after its last commit;
    * past ``expires_at`` -> block;
    * ``commits_used >= max_commits`` -> block mutators;
    * grant from a different fixture generation -> block (a reset invalidates old authority);
    * the stored digest no longer matches the grant fields -> block (tamper evidence).
    """

    def block(invariant: str, reason: str, **evidence: Any) -> Decision:
        return make_decision(
            run_id,
            DecisionSource.LIFECYCLE,
            Outcome.BLOCK,
            reason,
            proposal_id=proposal_id,
            layer=Layer.RUNTIME,
            invariant=invariant,
            decisive=True,
            evidence={"grant_id": grant.grant_id, **evidence},
        )

    if grant.status == GrantStatus.EXHAUSTED:
        if tool_is_mutator:
            return block(
                "grant_exhausted",
                f"The grant's commit budget is used up ({grant.commits_used}/{grant.limits.max_commits}).",
            )
    elif grant.status != GrantStatus.ACTIVE:
        return block(
            "grant_inactive", f"The grant is {grant.status.value}, not active.", status=grant.status.value
        )
    if grant.expires_at <= utcnow():
        return block("grant_expired", "The grant has expired.", expires_at=grant.expires_at.isoformat())
    if tool_is_mutator and grant.commits_used >= grant.limits.max_commits:
        return block(
            "grant_exhausted",
            f"The grant's commit budget is used up ({grant.commits_used}/{grant.limits.max_commits}).",
        )
    if grant.fixture_generation != fixture_generation:
        return block(
            "fixture_generation",
            "The demo fixture was reset after this grant was issued; its authority no longer applies.",
            grant_generation=grant.fixture_generation,
            current_generation=fixture_generation,
        )
    if grant.grant_digest != compute_grant_digest(grant):
        return block("grant_tampered", "The grant's contents no longer match its digest.")
    return None


def assert_within_grant(
    grant: TaskGrant,
    requested_tools: list[str],
    requested_resources: dict[str, list[str]],
    *,
    run_id: str = "",
    proposal_id: str | None = None,
) -> Decision | None:
    """Remint guard: anything outside the ORIGINAL grant -> BLOCK (``no_authority_expansion``)."""
    extra_tools = sorted(set(requested_tools) - set(grant.allowed_tools))
    extra_resources: dict[str, list[str]] = {}
    for rtype, ids in requested_resources.items():
        permitted = set(grant.resources.get(rtype, [])) | set(grant.reviewable.get(rtype, []))
        extra = sorted(set(ids) - permitted)
        if extra:
            extra_resources[rtype] = extra
    if not extra_tools and not extra_resources:
        return None
    parts = []
    if extra_tools:
        parts.append("tools " + ", ".join(extra_tools))
    for rtype, ids in extra_resources.items():
        parts.append(f"{rtype} " + ", ".join(ids))
    return make_decision(
        run_id,
        DecisionSource.GRANT_SCOPE,
        Outcome.BLOCK,
        "A re-issued plan may not exceed the original grant; not covered: " + "; ".join(parts) + ".",
        proposal_id=proposal_id,
        layer=Layer.GRANT,
        invariant="no_authority_expansion",
        decisive=True,
        evidence={"grant_id": grant.grant_id, "extra_tools": extra_tools, "extra_resources": extra_resources},
    )
