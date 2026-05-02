"""Per-key usage dashboard endpoint (Sprint 10)."""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Header, HTTPException

from app.lib.auth import verify_api_key
from app.lib.usage import get_usage_today, get_usage_total, get_usage_last_n_days
from app.stages.cache import get_redis_client

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/me")
async def get_my_usage(
    x_api_key: Optional[str] = Header(None),
    days: int = 7,
):
    """
    Return usage statistics for the authenticated API key.

    Query params
    ------------
    days : int  Number of daily buckets to return (default 7, max 30)
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-Api-Key header")

    redis_client = await get_redis_client()

    try:
        key_record = await verify_api_key(x_api_key, redis_client)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    key_hash = key_record.hash
    days = min(max(days, 1), 30)

    today = await get_usage_today(redis_client, key_hash)
    total = await get_usage_total(redis_client, key_hash)
    history = await get_usage_last_n_days(redis_client, key_hash, days)

    return {
        "tier": key_record.tier,
        "today": today,
        "total": total,
        "history": history,
    }
