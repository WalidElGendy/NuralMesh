import asyncio

import pytest

from app.lib import metrics


@pytest.mark.asyncio
async def test_record_cache_hit_increments_correct_counter() -> None:
    await metrics.reset_metrics()

    await metrics.record_cache_hit("redis", 100)
    snapshot = await metrics.get_metrics()

    assert snapshot["cache_hits_redis"] == 1
    assert snapshot["cache_hits_qdrant"] == 0
    assert snapshot["estimated_cost_savings_usd"] == 0.0003


@pytest.mark.asyncio
async def test_get_metrics_returns_hit_rate() -> None:
    await metrics.reset_metrics()

    await metrics.record_cache_hit("redis", 100)
    await metrics.record_cache_hit("miss", 0)
    snapshot = await metrics.get_metrics()

    assert snapshot["cache_hit_rate"] == 0.5
    assert snapshot["cache_misses"] == 1


@pytest.mark.asyncio
async def test_concurrent_metric_updates_are_safe() -> None:
    await metrics.reset_metrics()

    await asyncio.gather(*(metrics.record_cache_hit("qdrant", 10) for _ in range(10)))
    snapshot = await metrics.get_metrics()

    assert snapshot["cache_hits_qdrant"] == 10
    assert snapshot["cache_hit_rate"] == 1.0
