"""
Escalation logic with circuit-breaker awareness and retry.

- Skips models whose circuit is OPEN.
- Uses retry_sync for transient errors before escalating.
- Records success/failure to circuit breaker after each attempt.
"""
from typing import Any
import litellm

from app.lib.router import pick_model, next_model
from app.lib.billing import record_usage
from app.lib.circuit_breaker import is_available, record_success, record_failure
from app.lib.retry import retry_sync, _is_retryable


async def call_with_escalation(
    prompt: str,
    category: str,
    tier: str,
    redis_client,
    key_hash: str,
    hint: str | None = None,
    stream: bool = False,
) -> tuple:
    """
    Returns (response_or_stream, model_used, total_tokens).
    Tries pick_model first; on litellm exception escalates through next_model.
    Skips OPEN circuits. Retries transient errors before escalating.
    Raises last exception if all models exhausted.
    """
    model, remaining = pick_model(category, tier, hint=hint)
    last_exc = None

    while model is not None:
        # Skip if circuit is open
        if not await is_available(redis_client, model):
            if remaining:
                model = next_model(remaining)
                remaining = remaining[1:]
            else:
                break
            continue

        try:
            def _call():
                return litellm.completion(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    stream=stream,
                )

            response = retry_sync(_call, max_retries=2, base_delay=0.5)

            # Record success to circuit breaker
            await record_success(redis_client, model)

            if stream:
                return (response, model, 0)

            # Non-stream: count tokens
            total_tokens = 0
            try:
                total_tokens = response.usage.total_tokens or 0
            except Exception:
                pass
            await record_usage(redis_client, key_hash, total_tokens)
            return (response, model, total_tokens)

        except Exception as exc:
            last_exc = exc
            # Record failure to circuit breaker
            await record_failure(redis_client, model)

            if remaining:
                model = next_model(remaining)
                remaining = remaining[1:]
            else:
                break

    raise last_exc
