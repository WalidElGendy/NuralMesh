"""Tests for app.lib.usage ledger (Sprint 10)."""
import pytest
import fakeredis.aioredis as fakeredis

from app.lib.usage import (
    increment_usage,
    get_usage_today,
    get_usage_total,
    get_usage_last_n_days,
    _parse_bucket,
)


@pytest.fixture
async def redis():
    r = fakeredis.FakeRedis()
    yield r
    await r.aclose()


# ---------------------------------------------------------------------------
# test_increment_updates_total
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_increment_updates_total(redis):
    await increment_usage(redis, "hash1", tokens=100, cost_usd=0.01)
    total = await get_usage_total(redis, "hash1")
    assert total["tokens"] == 100.0
    assert total["requests"] == 1.0
    assert abs(total["cost_usd"] - 0.01) < 1e-6


# ---------------------------------------------------------------------------
# test_increment_accumulates
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_increment_accumulates(redis):
    await increment_usage(redis, "hash2", tokens=50, cost_usd=0.005)
    await increment_usage(redis, "hash2", tokens=50, cost_usd=0.005)
    total = await get_usage_total(redis, "hash2")
    assert total["tokens"] == 100.0
    assert total["requests"] == 2.0


# ---------------------------------------------------------------------------
# test_get_usage_today_reflects_current_day
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_usage_today_reflects_current_day(redis):
    await increment_usage(redis, "hash3", tokens=200, cost_usd=0.02)
    today = await get_usage_today(redis, "hash3")
    assert today["tokens"] == 200.0
    assert today["requests"] == 1.0


# ---------------------------------------------------------------------------
# test_get_usage_last_n_days_length
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_usage_last_n_days_length(redis):
    history = await get_usage_last_n_days(redis, "hash4", days=5)
    assert len(history) == 5
    # each item has a date key
    for item in history:
        assert "date" in item


# ---------------------------------------------------------------------------
# test_parse_bucket_empty
# ---------------------------------------------------------------------------
def test_parse_bucket_empty():
    result = _parse_bucket({})
    assert result == {"tokens": 0.0, "requests": 0.0, "cost_usd": 0.0}
