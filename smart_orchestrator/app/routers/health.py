"""Health check endpoint for NeuralMesh Smart Orchestrator (Sprint 9)."""
import time
from fastapi import APIRouter
from app.stages.cache import get_redis_client

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """
    Returns service health with dependency status.
    Always returns 200  callers inspect the 'status' field.
    """
    start = time.monotonic()
    checks: dict = {}

    # Redis check
    try:
        redis = await get_redis_client()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    elapsed = round(time.monotonic() - start, 4)
    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"

    return {
        "status": overall,
        "checks": checks,
        "latency_s": elapsed,
    }


@router.get("/status")
async def status_check():
    """Launch checklist status endpoint; all dependency checks must be green."""

    return await health_check()
