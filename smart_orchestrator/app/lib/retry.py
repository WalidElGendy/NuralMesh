"""
Exponential backoff retry for LiteLLM calls.
Retries on transient errors (rate limits, timeouts, 5xx).
Does NOT retry on 4xx (bad request, auth) errors.
"""
import asyncio
import logging
import time
from typing import Callable, Any

logger = logging.getLogger(__name__)

# Errors that are worth retrying
RETRYABLE_SUBSTRINGS = (
    "rate limit",
    "ratelimit",
    "timeout",
    "timed out",
    "service unavailable",
    "internal server error",
    "503",
    "529",
    "overloaded",
    "connection error",
    "temporarily unavailable",
)

# Default retry config
DEFAULT_MAX_RETRIES = 2
DEFAULT_BASE_DELAY = 0.5    # seconds
DEFAULT_MAX_DELAY = 8.0     # seconds


def _is_retryable(exc: Exception) -> bool:
    """Return True if the exception looks transient."""
    msg = str(exc).lower()
    return any(substr in msg for substr in RETRYABLE_SUBSTRINGS)


async def retry_async(
    fn: Callable,
    *args,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    **kwargs,
) -> Any:
    """
    Call async or sync fn(*args, **kwargs) with exponential backoff.
    Returns the result on success.
    Raises the last exception if all retries are exhausted.
    """
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(max_retries + 1):
        try:
            if asyncio.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            else:
                return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries:
                logger.warning("retry_async: all %d retries exhausted: %s", max_retries, exc)
                break
            if not _is_retryable(exc):
                logger.debug("retry_async: non-retryable error, giving up: %s", exc)
                break
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.info("retry_async: attempt %d failed (%s), retrying in %.2fs", attempt + 1, exc, delay)
            await asyncio.sleep(delay)
    raise last_exc


def retry_sync(
    fn: Callable,
    *args,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    **kwargs,
) -> Any:
    """
    Call sync fn(*args, **kwargs) with exponential backoff (blocking sleep).
    Returns the result on success.
    Raises the last exception if all retries are exhausted.
    """
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries:
                logger.warning("retry_sync: all %d retries exhausted: %s", max_retries, exc)
                break
            if not _is_retryable(exc):
                logger.debug("retry_sync: non-retryable error, giving up: %s", exc)
                break
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.info("retry_sync: attempt %d failed (%s), retrying in %.2fs", attempt + 1, exc, delay)
            time.sleep(delay)
    raise last_exc
