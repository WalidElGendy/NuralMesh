"""
Circuit Breaker for LLM model calls.

States: CLOSED (normal), OPEN (failing, skip), HALF_OPEN (testing recovery).
State is stored in Redis so all workers share the same view.
"""
import time
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# Thresholds
FAILURE_THRESHOLD = 3       # failures before OPEN
SUCCESS_THRESHOLD = 1       # successes in HALF_OPEN before CLOSED
TIMEOUT_SECONDS = 30        # seconds to stay OPEN before trying HALF_OPEN

CB_PREFIX = "cb:"           # Redis key prefix: cb:<model>:state, cb:<model>:failures, etc.


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


async def get_state(redis_client, model: str) -> CircuitState:
    """Return current circuit state for a model."""
    state_key = f"{CB_PREFIX}{model}:state"
    opened_at_key = f"{CB_PREFIX}{model}:opened_at"

    raw = await redis_client.get(state_key)
    if raw is None:
        return CircuitState.CLOSED

    state = raw.decode() if isinstance(raw, bytes) else raw

    if state == CircuitState.OPEN:
        # Check if timeout has elapsed -> transition to HALF_OPEN
        opened_at_raw = await redis_client.get(opened_at_key)
        if opened_at_raw:
            opened_at = float(opened_at_raw.decode() if isinstance(opened_at_raw, bytes) else opened_at_raw)
            if time.time() - opened_at >= TIMEOUT_SECONDS:
                await redis_client.set(state_key, CircuitState.HALF_OPEN)
                logger.info("Circuit for %s -> HALF_OPEN", model)
                return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    return CircuitState(state)


async def record_success(redis_client, model: str) -> None:
    """Record a successful call; may close circuit."""
    state = await get_state(redis_client, model)
    if state == CircuitState.HALF_OPEN:
        successes_key = f"{CB_PREFIX}{model}:successes"
        count = await redis_client.incr(successes_key)
        if count >= SUCCESS_THRESHOLD:
            await _close(redis_client, model)
    elif state == CircuitState.CLOSED:
        # Reset failure count on success
        await redis_client.set(f"{CB_PREFIX}{model}:failures", 0)


async def record_failure(redis_client, model: str) -> None:
    """Record a failed call; may open circuit."""
    state = await get_state(redis_client, model)
    if state == CircuitState.OPEN:
        return  # Already open, nothing to do

    failures_key = f"{CB_PREFIX}{model}:failures"
    count = await redis_client.incr(failures_key)
    logger.debug("Circuit failure count for %s: %d", model, count)

    if count >= FAILURE_THRESHOLD:
        await _open(redis_client, model)


async def _open(redis_client, model: str) -> None:
    """Transition circuit to OPEN."""
    await redis_client.set(f"{CB_PREFIX}{model}:state", CircuitState.OPEN)
    await redis_client.set(f"{CB_PREFIX}{model}:opened_at", str(time.time()))
    await redis_client.set(f"{CB_PREFIX}{model}:failures", 0)
    logger.warning("Circuit for %s -> OPEN", model)


async def _close(redis_client, model: str) -> None:
    """Transition circuit to CLOSED."""
    await redis_client.set(f"{CB_PREFIX}{model}:state", CircuitState.CLOSED)
    await redis_client.set(f"{CB_PREFIX}{model}:failures", 0)
    await redis_client.set(f"{CB_PREFIX}{model}:successes", 0)
    logger.info("Circuit for %s -> CLOSED", model)


async def is_available(redis_client, model: str) -> bool:
    """Return True if the model circuit is not OPEN."""
    state = await get_state(redis_client, model)
    return state != CircuitState.OPEN


async def reset(redis_client, model: str) -> None:
    """Fully reset circuit state (for testing / admin)."""
    for suffix in ("state", "failures", "successes", "opened_at"):
        await redis_client.delete(f"{CB_PREFIX}{model}:{suffix}")
