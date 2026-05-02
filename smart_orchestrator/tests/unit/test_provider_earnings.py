"""Tests for app.lib.provider_earnings  USD earnings ledger for GPU providers."""
import pytest
import fakeredis.aioredis as fakeredis

from app.lib.provider_earnings import (
    accrue_earnings,
    get_provider_earnings,
    request_payout,
    list_pending_payouts,
    approve_payout,
    PAYOUT_MIN_USD,
    _compute_earnings_usd,
)


@pytest.fixture
def redis():
    return fakeredis.FakeRedis()


def test_compute_earnings_local_model():
    """Local models should earn at the local rate per 1k tokens."""
    usd = _compute_earnings_usd(1000, "llama-3.1-8b")
    assert usd > 0.0
    assert usd < 0.001   # local rate is very small


def test_compute_earnings_cloud_higher_than_local():
    """Cloud model earnings should exceed local model earnings for same tokens."""
    local = _compute_earnings_usd(1000, "llama-3.1-8b")
    cloud = _compute_earnings_usd(1000, "claude-sonnet")
    assert cloud > local


@pytest.mark.asyncio
async def test_accrue_earnings_updates_balance(redis):
    """Accruing earnings should increase total_usd and pending_usd."""
    await accrue_earnings(redis, "node-001", 5000, "llama-3.1-8b")
    earnings = await get_provider_earnings(redis, "node-001")
    assert earnings["total_usd"] > 0.0
    assert earnings["pending_usd"] > 0.0
    assert earnings["total_tokens"] == 5000


@pytest.mark.asyncio
async def test_payout_request_below_minimum_returns_none(redis):
    """A payout request below the minimum threshold should return None."""
    # Accrue a tiny amount  not enough for payout
    await accrue_earnings(redis, "node-002", 1, "llama-3.1-8b")
    result = await request_payout(redis, "node-002", "Test User", "GB12BARC20201530093459", "BARCGB22")
    assert result is None


@pytest.mark.asyncio
async def test_payout_request_above_minimum_queues_record(redis):
    """A payout request above the minimum should return a payout record with pending status."""
    # Inject enough earnings manually to exceed minimum
    from app.lib.provider_earnings import PROVIDER_EARNINGS_KEY
    key = PROVIDER_EARNINGS_KEY.format(node_id="node-003")
    await redis.hset(key, mapping={"pending_usd": 5.00, "total_usd": 5.00, "lifetime_usd": 5.00, "total_tokens": 50000})

    record = await request_payout(redis, "node-003", "Test Provider", "US12345678", "021000021")
    assert record is not None
    assert record["status"] == "pending"
    assert record["amount_usd"] == 5.00
    assert record["node_id"] == "node-003"

    # Pending_usd should be cleared after queuing
    earnings = await get_provider_earnings(redis, "node-003")
    assert earnings["pending_usd"] == 0.0
