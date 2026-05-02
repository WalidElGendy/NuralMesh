"""Per-API-key usage ledger backed by Redis (Sprint 10).

Keys layout
-----------
usage:{key_hash}:daily:{YYYY-MM-DD}   HASH  tokens requests cost_usd
usage:{key_hash}:hourly:{YYYY-MM-DDTHH}  HASH  tokens requests
usage:{key_hash}:total                HASH  tokens requests cost_usd
"""
from __future__ import annotations

import datetime
from typing import Any


# --------------------------------------------------------------------------- #
# write helpers
# --------------------------------------------------------------------------- #

async def increment_usage(
    redis_client,
    key_hash: str,
    tokens: int,
    cost_usd: float = 0.0,
    model: str = "unknown",
) -> None:
    """Atomically record token + cost usage for a key across all buckets."""
    now = datetime.datetime.utcnow()
    day_bucket = now.strftime("%Y-%m-%d")
    hour_bucket = now.strftime("%Y-%m-%dT%H")

    pipe = redis_client.pipeline()

    # daily
    daily_key = f"usage:{key_hash}:daily:{day_bucket}"
    pipe.hincrbyfloat(daily_key, "tokens", tokens)
    pipe.hincrbyfloat(daily_key, "requests", 1)
    pipe.hincrbyfloat(daily_key, "cost_usd", cost_usd)
    pipe.expire(daily_key, 90 * 86400)  # 90-day TTL

    # hourly
    hourly_key = f"usage:{key_hash}:hourly:{hour_bucket}"
    pipe.hincrbyfloat(hourly_key, "tokens", tokens)
    pipe.hincrbyfloat(hourly_key, "requests", 1)
    pipe.expire(hourly_key, 7 * 86400)  # 7-day TTL

    # lifetime totals
    total_key = f"usage:{key_hash}:total"
    pipe.hincrbyfloat(total_key, "tokens", tokens)
    pipe.hincrbyfloat(total_key, "requests", 1)
    pipe.hincrbyfloat(total_key, "cost_usd", cost_usd)

    await pipe.execute()


# --------------------------------------------------------------------------- #
# read helpers
# --------------------------------------------------------------------------- #

async def get_usage_today(redis_client, key_hash: str) -> dict[str, float]:
    """Return today's usage bucket (tokens, requests, cost_usd)."""
    day_bucket = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    daily_key = f"usage:{key_hash}:daily:{day_bucket}"
    raw = await redis_client.hgetall(daily_key)
    return _parse_bucket(raw)


async def get_usage_total(redis_client, key_hash: str) -> dict[str, float]:
    """Return lifetime totals for the key."""
    total_key = f"usage:{key_hash}:total"
    raw = await redis_client.hgetall(total_key)
    return _parse_bucket(raw)


async def get_usage_last_n_days(
    redis_client, key_hash: str, days: int = 7
) -> list[dict[str, Any]]:
    """Return per-day buckets for the last N days (newest first)."""
    results = []
    for delta in range(days):
        day = datetime.datetime.utcnow() - datetime.timedelta(days=delta)
        day_str = day.strftime("%Y-%m-%d")
        daily_key = f"usage:{key_hash}:daily:{day_str}"
        raw = await redis_client.hgetall(daily_key)
        bucket = _parse_bucket(raw)
        bucket["date"] = day_str
        results.append(bucket)
    return results


# --------------------------------------------------------------------------- #
# internals
# --------------------------------------------------------------------------- #

def _parse_bucket(raw: dict) -> dict[str, float]:
    """Decode Redis byte strings to floats."""
    out: dict[str, float] = {"tokens": 0.0, "requests": 0.0, "cost_usd": 0.0}
    for k, v in raw.items():
        key = k.decode() if isinstance(k, bytes) else k
        try:
            out[key] = float(v)
        except (ValueError, TypeError):
            pass
    return out
