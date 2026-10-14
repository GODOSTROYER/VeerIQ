"""ArmorIQ latency split for /api/metrics (plan binding vs enforce vs token issuance)."""

from __future__ import annotations

from typing import Any

from rewindsafe.runtime import db
from rewindsafe.runtime.receipts import percentile

_GROUPS = {
    "plan_binding": ("armoriq.sdk.plan_binding",),
    "enforce": ("armoriq.backend.enforce",),
    "issuance": ("armoriq.backend.token_issuance",),
}


def _summary(values: list[float], count: int) -> dict[str, Any]:
    return {"p50": percentile(values, 0.5), "p95": percentile(values, 0.95), "count": count}


def armoriq_split(tenant_id: str | None = None) -> tuple[dict[str, Any], bool]:
    """Returns ({plan_binding, enforce, issuance}, any_simulated). Simulated decisions are counted, never timed."""
    with db.connection() as conn:
        if tenant_id is None:
            rows = conn.execute(
                "SELECT source, simulated, (body->>'latency_ms') AS latency "
                "FROM runtime.decisions WHERE layer = 'armoriq'"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT d.source, d.simulated, (d.body->>'latency_ms') AS latency "
                "FROM runtime.decisions d JOIN runtime.runs r ON r.run_id = d.run_id "
                "JOIN runtime.task_grants g ON g.grant_id = r.grant_id "
                "WHERE d.layer = 'armoriq' AND g.tenant_id = %s",
                (tenant_id,),
            ).fetchall()
    lat: dict[str, list[float]] = {k: [] for k in _GROUPS}
    cnt: dict[str, int] = dict.fromkeys(_GROUPS, 0)
    simulated = False
    for r in rows:
        if r["simulated"]:
            simulated = True
            continue
        for group, sources in _GROUPS.items():
            if r["source"] in sources:
                cnt[group] += 1
                try:
                    if r["latency"] is not None:
                        lat[group].append(float(r["latency"]))
                except (TypeError, ValueError):
                    pass
    split = {
        "plan_binding": {"count": cnt["plan_binding"]},  # local SDK check against the signed plan: no network
        "enforce": _summary(lat["enforce"], cnt["enforce"]),
        "issuance": _summary(lat["issuance"], cnt["issuance"]),
    }
    return split, simulated
