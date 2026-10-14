"""Health, status, scenarios and aggregate metrics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from rewindsafe.api import auth, evidence
from rewindsafe.api import metrics as metrics_mod
from rewindsafe.api.deps import get_workflow_adapter
from rewindsafe.api.status import build_system_status
from rewindsafe.contracts import Identity, ScenarioSpec
from rewindsafe.runtime import receipts

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"ok": True}


@router.get("/system/status")
def system_status() -> dict[str, Any]:
    return build_system_status()


@router.get("/scenarios", response_model=list[ScenarioSpec])
def scenarios() -> list[ScenarioSpec]:
    return sorted(get_workflow_adapter().scenarios(), key=lambda s: s.order)


@router.get("/metrics")
def metrics(identity: Identity = Depends(auth.current_identity)) -> dict[str, Any]:
    data = receipts.global_metrics(tenant_id=identity.tenant_id)
    split, simulated = metrics_mod.armoriq_split(tenant_id=identity.tenant_id)
    data["armoriq"] = split
    data["simulated"] = simulated or bool(data.get("armoriq_latency_ms", {}).get("simulated_count"))
    return data


@router.get("/evidence/live")
def evidence_live() -> dict[str, Any]:
    """Recorded live ArmorIQ evidence (sanitized) plus the gateway's cached readiness."""
    return evidence.live_evidence()
