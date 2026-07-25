"""Public mesh telemetry — GET /api/mesh/status.

The console shows, on every answer, which node served it and what the network
looked like at the time. That is the one thing a decentralised inference
product can show that a centralised one cannot, and the beta had no endpoint
for it — so the mesh was invisible inside its own product.

This exposes only aggregate, non-identifying provider state: node id, region
hint, status, latency percentiles, success rate and tokens served. No emails,
no payout details, no hostnames.

Wire into api.py:
    from mesh_status import router as _mesh_router
    app.include_router(_mesh_router)
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter
from pydantic import BaseModel

import mesh_router
from api import get_supabase_client

router = APIRouter(prefix="/api/mesh", tags=["mesh"])
logger = logging.getLogger(__name__)

CACHE_TTL_S = 20
_cache: tuple[float, dict] | None = None

# What actually answers chat traffic today. The landing page says "Llama 3.3
# 70B on the sovereign GPU mesh" while agents.py calls SiliconFlow; report the
# truth here rather than implying node provenance that did not happen.
FALLBACK_LABEL = os.environ.get("NM_PROVIDER_LABEL", "siliconflow")
FALLBACK_MODEL = os.environ.get("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3.1")


class MeshStatus(BaseModel):
    providers: list[dict]
    online: int
    registered: int
    capacity: int = 0
    latency_p50_ms: int | None = None
    tokens_today: int = 0
    fallback: dict
    # The number the business is steered by: what share of tokens the network
    # served itself today, and what the remainder cost in cash.
    sovereignty: dict = {}
    fallback_reasons: list[dict] = []


@router.get("/status", response_model=MeshStatus)
def mesh_status():
    global _cache
    now = time.time()
    if _cache and now - _cache[0] < CACHE_TTL_S:
        return MeshStatus(**_cache[1])

    rows: list[dict] = []
    try:
        res = (
            get_supabase_client()
            .table("providers")
            .select(
                "node_id,status,latency_p50_ms,latency_p95_ms,success_rate,"
                "tokens_today,gpu_info,last_seen_at,max_concurrent,cooldown_until"
            )
            .order("tokens_today", desc=True)
            .limit(24)
            .execute()
        )
        rows = res.data or []
    except Exception:
        logger.warning("mesh_status_query_failed", exc_info=True)

    providers = [
        {
            "node_id": r.get("node_id"),
            "status": r.get("status", "offline"),
            "latency_p50_ms": r.get("latency_p50_ms"),
            "latency_p95_ms": r.get("latency_p95_ms"),
            "success_rate": r.get("success_rate"),
            "tokens_today": r.get("tokens_today") or 0,
            "gpu": (r.get("gpu_info") or {}).get("model"),
        }
        for r in rows
    ]

    sb = None
    try:
        sb = get_supabase_client()
    except Exception:
        logger.warning("mesh_status_client_failed", exc_info=True)
    sov = mesh_router.sovereignty(sb, days=14) if sb else {"available": False}
    reasons = mesh_router.fallback_reasons(sb) if sb else []

    online = [p for p in providers if p["status"] == "online"]
    lat = [p["latency_p50_ms"] for p in online if p.get("latency_p50_ms")]

    payload = {
        "providers": providers,
        "online": len(online),
        "registered": len(providers),
        "latency_p50_ms": round(sum(lat) / len(lat)) if lat else None,
        "tokens_today": sum(p["tokens_today"] for p in providers),
        "capacity": sum(int(r.get("max_concurrent") or 1) for r in rows
                        if r.get("status") == "online"),
        # Honest about what is actually serving chat right now.
        "fallback": {"provider": FALLBACK_LABEL, "model": FALLBACK_MODEL,
                     "active": len(online) == 0,
                     "mesh_model": mesh_router.MESH_MODEL},
        "sovereignty": sov,
        "fallback_reasons": reasons,
    }
    _cache = (now, payload)
    return MeshStatus(**payload)
