from typing import Any
import litellm
from app.lib.router import pick_model, next_model
from app.lib.billing import record_usage


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
    Raises last exception if all models exhausted.
    """
    model, remaining = pick_model(category, tier, hint=hint)
    last_exc = None

    while model is not None:
        try:
            response = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                stream=stream,
            )
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
            if remaining:
                model = next_model(remaining)
                remaining = remaining[1:]
            else:
                break

    raise last_exc
