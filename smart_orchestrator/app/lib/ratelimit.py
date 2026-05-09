from __future__ import annotations

import time
from typing import Any

from fastapi import HTTPException

from app.config import BETA_REQUESTS_PER_DAY, BETA_REQUESTS_PER_MINUTE
from app.lib.logger import get_logger
from app.models.schemas import RateLimitResult

logger = get_logger(__name__)

TIER_LIMITS = {
    "free": 10,
    "beta": BETA_REQUESTS_PER_MINUTE,
    "pro": 60,
    "admin": 9999,
}

BETA_DAILY_LIMIT = BETA_REQUESTS_PER_DAY
DAY_SECONDS = 86400
WINDOW_SECONDS = 60


class RateLimiter:
    """Redis sorted-set sliding-window rate limiter.

    Args:
        redis_client: Existing Redis client from app.stages.cache.get_redis_client.
        tier: API key tier.

    Returns:
        Limiter instance for per-key request enforcement.

    Cost/quality target:
        Enforce per-key requests/minute in Redis with fail-open behavior on outages.
    """

    def __init__(self, redis_client: Any, tier: str = "free") -> None:
        self.redis_client = redis_client
        self.tier = tier

    async def check_and_increment(self, key_hash: str, tier: str | None = None) -> RateLimitResult:
        """Check and increment one key's sliding-window request count.

        Args:
            key_hash: SHA-256 hash of the raw API key.
            tier: Optional tier override.

        Returns:
            RateLimitResult with limit, remaining, and reset timestamp.

        Cost/quality target:
            One Redis sorted-set transaction-equivalent sequence per protected request.
        """
        selected_tier = tier or self.tier
        limit = TIER_LIMITS.get(selected_tier, TIER_LIMITS["free"])
        now = time.time()
        reset_at = int(now + WINDOW_SECONDS)
        key = f"ratelimit:{key_hash}"
        member = f"{now}:{id(self)}"

        try:
            await self.redis_client.zremrangebyscore(key, 0, now - WINDOW_SECONDS)
            current = await self.redis_client.zcard(key)
            if current >= limit:
                result = RateLimitResult(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    reset_at=reset_at,
                )
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={
                        "X-RateLimit-Limit": str(result.limit),
                        "X-RateLimit-Remaining": str(result.remaining),
                        "X-RateLimit-Reset": str(result.reset_at),
                    },
                )
            await self.redis_client.zadd(key, {member: now})
            await self.redis_client.expire(key, WINDOW_SECONDS)
            remaining = max(limit - int(current) - 1, 0)
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=remaining,
                reset_at=reset_at,
            )
        except HTTPException:
            raise
        except Exception as error:
            logger.warning(
                "rate_limit_fail_open",
                key_hash=key_hash[:16],
                error=type(error).__name__,
            )
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit,
                reset_at=reset_at,
            )


async def check_and_increment(key_hash: str, tier: str, redis_client: Any) -> RateLimitResult:
    """Convenience wrapper for one-off rate-limit checks.

    Args:
        key_hash: SHA-256 hash of the raw API key.
        tier: API key tier.
        redis_client: Existing Redis client.

    Returns:
        RateLimitResult for the current request.

    Cost/quality target:
        Keeps FastAPI dependencies concise without hiding Redis behavior.
    """
    return await RateLimiter(redis_client, tier=tier).check_and_increment(key_hash, tier)
