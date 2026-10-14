"""Verification suite endpoints (feeds the Proof board)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from rewindsafe.api import auth, verification_jobs
from rewindsafe.api.errors import conflict, not_found
from rewindsafe.contracts import Identity

router = APIRouter(prefix="/api/verification", tags=["verification"])


@router.get("/latest")
def latest() -> dict[str, Any] | None:
    return verification_jobs.latest()


@router.post("/run", dependencies=[Depends(auth.refuse_in_production)])  # resets demo data: demo-only
def run(_: Identity = Depends(auth.require_demo_operator)) -> dict[str, str]:
    verification_id = verification_jobs.start()
    if verification_id is None:
        raise conflict("A verification run is already in progress.", "verification_running")
    return {"verification_id": verification_id}


@router.get("/{verification_id}")
def get(verification_id: str) -> dict[str, Any]:
    found = verification_jobs.get(verification_id)
    if found is None:
        raise not_found("Verification run not found.")
    return found
