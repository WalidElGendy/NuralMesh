import time

import pytest
from fastapi import HTTPException

from app.lib.ratelimit import RateLimiter


class FakeRedis:
    def __init__(self) -> None:
        self.members: dict[str, dict[str, float]] = {}

    async def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> None:
        bucket = self.members.setdefault(key, {})
        for member, score in list(bucket.items()):
            if min_score <= score <= max_score:
                del bucket[member]

    async def zcard(self, key: str) -> int:
        return len(self.members.setdefault(key, {}))

    async def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self.members.setdefault(key, {}).update(mapping)

    async def expire(self, key: str, seconds: int) -> None:
        return None


class BrokenRedis:
    async def zremrangebyscore(self, *args, **kwargs):
        raise ConnectionError("redis down")


@pytest.mark.asyncio
async def test_under_limit() -> None:
    limiter = RateLimiter(FakeRedis(), tier="free")
    result = await limiter.check_and_increment("hash", "free")
    assert result.allowed is True
    assert result.remaining == 9


@pytest.mark.asyncio
async def test_at_limit() -> None:
    limiter = RateLimiter(FakeRedis(), tier="free")
    for _ in range(10):
        result = await limiter.check_and_increment("hash", "free")
    assert result.allowed is True
    assert result.remaining == 0
    with pytest.raises(HTTPException) as exc:
        await limiter.check_and_increment("hash", "free")
    assert exc.value.status_code == 429
    assert exc.value.headers["X-RateLimit-Limit"] == "10"


@pytest.mark.asyncio
async def test_redis_unavailable() -> None:
    limiter = RateLimiter(BrokenRedis(), tier="free")
    result = await limiter.check_and_increment("hash", "free")
    assert result.allowed is True


@pytest.mark.asyncio
async def test_tier_limits() -> None:
    limiter = RateLimiter(FakeRedis(), tier="admin")
    result = await limiter.check_and_increment("hash", "admin")
    assert result.limit == 9999
    assert result.reset_at >= int(time.time())
