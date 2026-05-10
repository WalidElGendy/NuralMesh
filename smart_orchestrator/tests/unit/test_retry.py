"""Tests for app.lib.retry"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from app.lib.retry import retry_sync, retry_async, _is_retryable


def test_is_retryable_rate_limit():
    """Rate limit errors should be retryable."""
    exc = Exception("rate limit exceeded")
    assert _is_retryable(exc) is True


def test_is_retryable_auth_error():
    """Auth errors (401) should NOT be retryable."""
    exc = Exception("401 unauthorized invalid api key")
    assert _is_retryable(exc) is False


def test_retry_sync_succeeds_on_first_try():
    """retry_sync should return value immediately on success."""
    call_count = 0
    def fn():
        nonlocal call_count
        call_count += 1
        return "ok"
    result = retry_sync(fn, max_retries=2, base_delay=0.0)
    assert result == "ok"
    assert call_count == 1


def test_retry_sync_raises_non_retryable_immediately():
    """Non-retryable errors should not be retried."""
    call_count = 0
    def fn():
        nonlocal call_count
        call_count += 1
        raise ValueError("401 unauthorized")
    with pytest.raises(ValueError):
        retry_sync(fn, max_retries=3, base_delay=0.0)
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_async_retries_transient_error():
    """retry_async should retry on transient errors."""
    call_count = 0
    async def fn():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("rate limit exceeded")
        return "success"
    result = await retry_async(fn, max_retries=3, base_delay=0.0)
    assert result == "success"
    assert call_count == 3
