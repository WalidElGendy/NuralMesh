"""Tests for app.lib.circuit_breaker"""
import pytest
import asyncio
import fakeredis.aioredis as fakeredis

from app.lib.circuit_breaker import (
    get_state, record_success, record_failure,
    is_available, reset, CircuitState,
    FAILURE_THRESHOLD,
)


@pytest.fixture
def redis():
    return fakeredis.FakeRedis()


@pytest.mark.asyncio
async def test_initial_state_is_closed(redis):
    """New model circuit should be CLOSED."""
    state = await get_state(redis, "test-model")
    assert state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_record_failures_opens_circuit(redis):
    """After FAILURE_THRESHOLD failures the circuit should be OPEN."""
    for _ in range(FAILURE_THRESHOLD):
        await record_failure(redis, "test-model")
    state = await get_state(redis, "test-model")
    assert state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_open_circuit_not_available(redis):
    """An OPEN circuit should report is_available=False."""
    for _ in range(FAILURE_THRESHOLD):
        await record_failure(redis, "blocked-model")
    available = await is_available(redis, "blocked-model")
    assert available is False


@pytest.mark.asyncio
async def test_closed_circuit_is_available(redis):
    """A CLOSED circuit should report is_available=True."""
    available = await is_available(redis, "fresh-model")
    assert available is True


@pytest.mark.asyncio
async def test_reset_clears_state(redis):
    """reset() should clear all circuit state back to CLOSED."""
    for _ in range(FAILURE_THRESHOLD):
        await record_failure(redis, "reset-model")
    assert await get_state(redis, "reset-model") == CircuitState.OPEN
    await reset(redis, "reset-model")
    assert await get_state(redis, "reset-model") == CircuitState.CLOSED
