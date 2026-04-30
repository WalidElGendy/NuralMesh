"""Tests for app/lib/billing.py - Sprint 6"""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import fakeredis.aioredis as fakeredis
from app.lib.billing import (
    get_tier_for_price,
    record_usage,
    get_usage,
    handle_subscription_event,
    PRICE_TIER_MAP,
)
import os
os.environ.setdefault("STRIPE_FREE_PRICE_ID", "price_free")
os.environ.setdefault("STRIPE_PRO_PRICE_ID", "price_pro")
os.environ.setdefault("STRIPE_ADMIN_PRICE_ID", "price_admin")


def test_get_tier_for_known_price():
    assert get_tier_for_price("price_pro") == "pro"
    assert get_tier_for_price("price_free") == "free"
    assert get_tier_for_price("price_admin") == "admin"


def test_get_tier_for_unknown_price():
    assert get_tier_for_price("price_unknown_xyz") == "free"


@pytest.mark.asyncio
async def test_record_usage():
    redis = fakeredis.FakeRedis()
    await record_usage(redis, "testhash123", 42)
    data = await redis.hgetall("usage:testhash123")
    assert int(data[b"requests"]) == 1
    assert int(data[b"tokens_total"]) == 42


@pytest.mark.asyncio
async def test_get_usage():
    redis = fakeredis.FakeRedis()
    await redis.hset("usage:myhash", mapping={"requests": "5", "tokens_total": "100"})
    result = await get_usage(redis, "myhash")
    assert result.key_hash == "myhash"
    assert result.requests == 5
    assert result.tokens_total == 100


@pytest.mark.asyncio
async def test_handle_subscription_updated_upgrades_tier():
    redis = fakeredis.FakeRedis()
    await redis.set("billing:email:user@example.com", "hashxyz")
    await redis.hset("auth:keys:hashxyz", mapping={"tier": "free", "name": "test", "active": "1"})
    
    event = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "customer": "cus_test123",
                "items": {"data": [{"price": {"id": "price_pro"}}]},
            }
        },
    }
    
    with patch("app.lib.billing.stripe.Customer.retrieve") as mock_retrieve:
        mock_retrieve.return_value = {"email": "user@example.com"}
        result = await handle_subscription_event(event, redis)
    
    assert result == "upgraded"
    tier = await redis.hget("auth:keys:hashxyz", "tier")
    assert tier == b"pro"


@pytest.mark.asyncio
async def test_handle_subscription_deleted_resets_tier():
    redis = fakeredis.FakeRedis()
    await redis.set("billing:email:user2@example.com", "hash2")
    await redis.hset("auth:keys:hash2", mapping={"tier": "pro", "name": "test2", "active": "1"})
    
    event = {
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "customer": "cus_test456",
                "items": {"data": []},
            }
        },
    }
    
    with patch("app.lib.billing.stripe.Customer.retrieve") as mock_retrieve:
        mock_retrieve.return_value = {"email": "user2@example.com"}
        result = await handle_subscription_event(event, redis)
    
    assert result == "cancelled"
    tier = await redis.hget("auth:keys:hash2", "tier")
    assert tier == b"free"
