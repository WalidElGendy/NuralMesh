from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import ConnectionError

from app.models.schemas import CacheResult, ChatMessage, PipelineContext, PromptClassification
from app.stages.cache import cache_stage, write_cache


def make_context(sensitive: bool = False) -> PipelineContext:
    ctx = PipelineContext(
        subscriber_id="sub_demo_pro",
        messages=[ChatMessage(role="user", content="Explain semantic caching for inference.")],
    )
    ctx.classification = PromptClassification(
        domain="factual",
        complexity="simple",
        sensitive=sensitive,
        confidence=0.9,
    )
    return ctx


@pytest.mark.asyncio
async def test_redis_hit_skips_qdrant() -> None:
    redis_client = AsyncMock()
    redis_client.get.return_value = '{"answer":"cached","tokens_saved":42}'
    qdrant_client = AsyncMock()

    result = await cache_stage(make_context(), redis_client=redis_client, qdrant_client=qdrant_client)

    assert result == CacheResult(hit=True, answer="cached", tokens_saved=42, source="redis", latency_ms=result.latency_ms)
    qdrant_client.query_points.assert_not_called()


@pytest.mark.asyncio
async def test_redis_miss_qdrant_hit() -> None:
    redis_client = AsyncMock()
    redis_client.get.return_value = None
    qdrant_client = AsyncMock()
    point = type("Point", (), {"payload": {"answer": "semantic", "tokens": 33}})()
    qdrant_client.query_points.return_value = type("Result", (), {"points": [point]})()

    result = await cache_stage(make_context(), redis_client=redis_client, qdrant_client=qdrant_client)

    assert result.hit is True
    assert result.source == "qdrant"
    assert result.answer == "semantic"


@pytest.mark.asyncio
async def test_redis_miss_qdrant_miss() -> None:
    redis_client = AsyncMock()
    redis_client.get.return_value = None
    qdrant_client = AsyncMock()
    qdrant_client.query_points.return_value = type("Result", (), {"points": []})()

    result = await cache_stage(make_context(), redis_client=redis_client, qdrant_client=qdrant_client)

    assert result.hit is False
    assert result.source == "miss"


@pytest.mark.asyncio
async def test_sensitive_never_hits_cache() -> None:
    redis_client = AsyncMock()
    qdrant_client = AsyncMock()

    result = await cache_stage(make_context(sensitive=True), redis_client=redis_client, qdrant_client=qdrant_client)

    assert result.hit is False
    redis_client.get.assert_not_called()
    qdrant_client.query_points.assert_not_called()


@pytest.mark.asyncio
async def test_redis_unavailable_falls_through_to_qdrant() -> None:
    redis_client = AsyncMock()
    redis_client.get.side_effect = ConnectionError("down")
    qdrant_client = AsyncMock()
    point = type("Point", (), {"payload": {"answer": "semantic", "tokens": 12}})()
    qdrant_client.query_points.return_value = type("Result", (), {"points": [point]})()

    result = await cache_stage(make_context(), redis_client=redis_client, qdrant_client=qdrant_client)

    assert result.hit is True
    assert result.source == "qdrant"


@pytest.mark.asyncio
async def test_qdrant_unavailable_returns_miss() -> None:
    redis_client = AsyncMock()
    redis_client.get.return_value = None
    qdrant_client = AsyncMock()
    qdrant_client.query_points.side_effect = RuntimeError("down")

    result = await cache_stage(make_context(), redis_client=redis_client, qdrant_client=qdrant_client)

    assert result.hit is False
    assert result.source == "miss"


@pytest.mark.asyncio
async def test_write_cache_writes_redis_and_qdrant_and_respects_sensitive_guard() -> None:
    ctx = make_context()
    ctx.final_answer = "This answer is long enough to be cached safely."
    redis_client = AsyncMock()
    qdrant_client = AsyncMock()

    await write_cache(ctx, redis_client=redis_client, qdrant_client=qdrant_client)

    redis_client.setex.assert_called_once()
    qdrant_client.upsert.assert_called_once()

    sensitive = make_context(sensitive=True)
    sensitive.final_answer = "This answer is long enough to be cached safely."
    redis_client.reset_mock()
    qdrant_client.reset_mock()

    await write_cache(sensitive, redis_client=redis_client, qdrant_client=qdrant_client)

    redis_client.setex.assert_not_called()
    qdrant_client.upsert.assert_not_called()
