"""Tests for dashboard_data helpers."""
import json
import pytest
import fakeredis
from app.lib.dashboard_data import (
    get_user_stats, get_user_tier_info,
    get_provider_dashboard, get_network_stats,
)


@pytest.fixture
def redis():
    return fakeredis.FakeRedis()


@pytest.mark.asyncio
async def test_get_user_stats_empty(redis):
    stats = await get_user_stats("nonexistent_hash", redis)
    assert stats["total_tokens"] == 0
    assert stats["total_requests"] == 0
    assert stats["total_cost_usd"] == 0.0
    assert stats["model_breakdown"] == {}
    assert stats["recent_history"] == []


@pytest.mark.asyncio
async def test_get_user_tier_info_default(redis):
    info = await get_user_tier_info("nonexistent_hash", redis)
    assert info["tier"] == "free"
    assert info["rate_limit"] == 60


@pytest.mark.asyncio
async def test_get_user_tier_info_pro(redis):
    redis.hset("apikey:testhash", mapping={"tier": "pro"})
    info = await get_user_tier_info("testhash", redis)
    assert info["tier"] == "pro"
    assert info["rate_limit"] == 300


@pytest.mark.asyncio
async def test_get_provider_dashboard_empty(redis):
    data = await get_provider_dashboard("node-xyz", redis)
    assert data["node_id"] == "node-xyz"
    assert data["total_earned_usd"] == 0.0
    assert data["pending_payout_usd"] == 0.0
    assert data["token_count"] == 0


@pytest.mark.asyncio
async def test_get_provider_dashboard_with_earnings(redis):
    redis.hset("provider:earnings:node-abc", mapping={
        "total_earned_usd": "5.2345",
        "pending_payout_usd": "3.0",
        "paid_out_usd": "2.0",
        "token_count": "50000",
    })
    data = await get_provider_dashboard("node-abc", redis)
    assert data["total_earned_usd"] == 5.2345
    assert data["token_count"] == 50000


@pytest.mark.asyncio
async def test_get_network_stats(redis):
    stats = await get_network_stats(redis)
    assert "active_nodes" in stats
    assert "uptime_pct" in stats
    assert stats["uptime_pct"] == 99.7
