"""Grants, runs, event streaming and evidence export."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from rewindsafe.api import auth, queries, sse
from rewindsafe.api.deps import (
    agent_api,
    get_workflow_adapter,
    load_grant_for,
    load_run_for,
    require_principal,
    resolve_planner,
    translate_domain_errors,
)
from rewindsafe.api.errors import conflict, forbidden, not_found
from rewindsafe.contracts import GrantStatus, Identity, Run, RunEvent, TaskGrant
from rewindsafe.runtime import db, events, grants, receipts, sealed_evidence
from rewindsafe.runtime.adapter import get_adapter

router = APIRouter(prefix="/api", tags=["grants and runs"])


class DraftBody(BaseModel):
    scenario_id: str
    auto_reset: bool = False


class StartRunBody(BaseModel):
    grant_id: str
    planner: Literal["auto", "scripted", "llm"] | None = None


# ─── grants ────────────────────────────────────────────────────────────────


_DIRTY_SQL = """
    SELECT (
        EXISTS (SELECT 1 FROM runtime.receipts
                WHERE fixture_generation = (SELECT generation FROM runtime.fixture_state LIMIT 1))
        OR EXISTS (SELECT 1 FROM authority.record_holds WHERE active)
        OR COALESCE((SELECT max(epoch) FROM authority.tenant_epochs), 1) > 1
    ) AS dirty
"""


def fixture_status(adapter: Any) -> dict[str, Any]:
    """{dirty, repaired_orders, note}: the adapter's answer (C6), else a conservative SQL fallback."""
    fn = getattr(adapter, "fixture_status", None)
    if callable(fn):
        try:
            return dict(fn())
        except Exception:  # advisory: never block drafting on a status probe
            pass
    try:
        with db.connection() as conn:
            row = conn.execute(_DIRTY_SQL).fetchone()
        dirty = bool(row and row["dirty"])
    except Exception:
        dirty = False
    return {"dirty": dirty, "repaired_orders": [], "note": "Fixture already modified by an earlier run." if dirty else ""}


@router.post("/grants/draft")
def draft_grant(body: DraftBody, identity: Identity = Depends(auth.require_operator)) -> dict[str, Any]:
    adapter = get_workflow_adapter()
    scenario = next((s for s in adapter.scenarios() if s.scenario_id == body.scenario_id), None)
    if scenario is None:
        raise not_found(f"Unknown scenario '{body.scenario_id}'.")
    status = fixture_status(adapter)
    fixture_reset = False
    if status.get("dirty") and body.auto_reset:
        auth.require_demo_operator(identity)
        from rewindsafe.api import routes_admin

        routes_admin.safe_reset(identity.identity_id)
        fixture_reset = True
        status = fixture_status(adapter)
    with translate_domain_errors():
        grant = grants.create_draft(adapter, scenario, identity)
    if grant.tenant_id != identity.tenant_id:
        raise forbidden("This scenario targets a different tenant than your session.", "tenant_mismatch")
    payload = jsonable_encoder(grant)
    payload["fixture"] = status
    payload["fixture_reset"] = fixture_reset
    return payload


@router.post("/grants/{grant_id}/authorize", response_model=TaskGrant)
def authorize_grant(grant_id: str, identity: Identity = Depends(auth.require_operator)) -> TaskGrant:
    grant = load_grant_for(identity, grant_id)
    require_principal(identity, grant)
    if grant.status != GrantStatus.DRAFT:
        raise conflict(f"Grant is {grant.status.value}; only a draft grant can be authorized.", "grant_not_draft")
    with translate_domain_errors():
        return grants.authorize(grant_id, identity)


@router.get("/grants/{grant_id}", response_model=TaskGrant)
def get_grant(grant_id: str, identity: Identity = Depends(auth.current_identity)) -> TaskGrant:
    return load_grant_for(identity, grant_id)


# ─── runs ──────────────────────────────────────────────────────────────────


@router.post("/runs", response_model=Run)
def start_run(body: StartRunBody, identity: Identity = Depends(auth.require_operator)) -> Run:
    grant = load_grant_for(identity, body.grant_id)
    require_principal(identity, grant)
    if grant.status != GrantStatus.ACTIVE:
        raise conflict(
            f"Grant is {grant.status.value}; authorize it before starting the agent.", "grant_not_active"
        )
    workflow_adapter = get_adapter(grant.workflow)
    scenario = next((s for s in workflow_adapter.scenarios() if s.scenario_id == grant.scenario_id), None)
    planner = resolve_planner(body.planner, scenario.default_planner if scenario else "auto")
    with translate_domain_errors():
        return agent_api().start_run(grant.grant_id, identity, planner=planner)


@router.get("/runs", response_model=list[Run])
def list_runs(identity: Identity = Depends(auth.current_identity)) -> list[Run]:
    return queries.list_runs_for_tenant(identity.tenant_id)


@router.get("/runs/{run_id}")
def run_detail(run_id: str, identity: Identity = Depends(auth.current_identity)) -> dict[str, Any]:
    run = load_run_for(identity, run_id)
    grant = grants.load(run.grant_id)
    detail = queries.assemble_run_detail(run, grant, queries.run_rows(run_id))
    detail["metrics"] = receipts.run_metrics(run_id)
    detail["protected_checks"] = [
        c.model_dump(mode="json") for c in get_adapter(run.workflow).protected_checks(identity.tenant_id)
    ]
    return detail


@router.post("/runs/{run_id}/cancel", response_model=Run)
def cancel_run(run_id: str, identity: Identity = Depends(auth.require_operator)) -> Run:
    load_run_for(identity, run_id)
    with translate_domain_errors():
        return agent_api().cancel_run(run_id, identity)


# ─── events ────────────────────────────────────────────────────────────────


@router.get("/runs/{run_id}/events/list", response_model=list[RunEvent])
def list_run_events(
    run_id: str,
    after: int = Query(0, ge=0),
    identity: Identity = Depends(auth.current_identity),
) -> list[RunEvent]:
    load_run_for(identity, run_id)
    return events.list_events(run_id, after)


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
    after: int = Query(0, ge=0),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    identity: Identity = Depends(auth.current_identity),
):
    await asyncio.to_thread(load_run_for, identity, run_id)
    start = sse.resume_position(after, last_event_id)
    finished = await asyncio.to_thread(queries.finished_seq, run_id)
    if finished is not None and start >= finished:
        # The client already has everything. 204 tells EventSource to stop
        # reconnecting instead of looping on a closed stream.
        return Response(status_code=204)
    return StreamingResponse(
        sse.stream_events(events.list_events, run_id, start, is_disconnected=request.is_disconnected),
        media_type="text/event-stream",
        headers=sse.SSE_HEADERS,
    )


# ─── evidence ──────────────────────────────────────────────────────────────


@router.get("/evidence/signing-public-key")
def signing_public_key(identity: Identity = Depends(auth.current_identity)) -> Response:
    """Publish the persistent export signer's public key to an authenticated caller."""
    return Response(
        content=sealed_evidence.public_key_pem(),
        media_type="application/x-pem-file",
        headers={
            "Content-Disposition": 'attachment; filename="workspace-public-key.pem"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/runs/{run_id}/evidence")
def run_evidence(run_id: str, identity: Identity = Depends(auth.current_identity)) -> JSONResponse:
    load_run_for(identity, run_id)
    evidence = receipts.build_evidence(run_id)
    return JSONResponse(
        content=jsonable_encoder(evidence),
        headers={"Content-Disposition": f'attachment; filename="rewindsafe-evidence-{run_id}.json"'},
    )


@router.get("/runs/{run_id}/sealed-evidence")
def run_sealed_evidence(run_id: str, identity: Identity = Depends(auth.current_identity)) -> JSONResponse:
    load_run_for(identity, run_id)
    evidence = sealed_evidence.build_sealed_evidence(run_id)
    return JSONResponse(
        content=jsonable_encoder(evidence),
        headers={"Content-Disposition": f'attachment; filename="rewindsafe-sealed-evidence-{run_id}.json"'},
    )
