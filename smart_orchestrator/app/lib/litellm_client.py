import asyncio
import hashlib
import os
from typing import Any

from app.config import MODEL_MAP
from app.lib.logger import get_logger
from app.models.schemas import ModelResponse

try:
    from litellm import acompletion, token_counter
except Exception:  # pragma: no cover - dependency is installed in normal runtime
    acompletion = None  # type: ignore[assignment]
    token_counter = None  # type: ignore[assignment]


logger = get_logger(__name__)


def _prompt_hash(messages: list[dict[str, str]]) -> str:
    return hashlib.sha256(str(messages).encode("utf-8")).hexdigest()[:16]


async def call_model(model_key: str, messages: list[dict[str, str]], timeout: int = 30) -> ModelResponse:
    """Call a model through LiteLLM using the configured model map.

    Args:
        model_key: Logical model key from route or prune stages.
        messages: Chat messages to send to LiteLLM.
        timeout: Request timeout in seconds.

    Returns:
        ModelResponse containing content and token usage.

    Cost/quality target:
        Local model call ~500 tokens, escalation to frontier ~2000 tokens; target
        <1000 average tokens per route call across the eval set.
    """
    if model_key not in MODEL_MAP:
        raise ValueError(f"Unknown model key: {model_key}")

    if os.environ.get("ROUTE_MODEL_PREFIX", "live") == "mock":
        return ModelResponse(content="[MOCK]", tokens=0, model=model_key)

    if acompletion is None:
        raise RuntimeError("litellm is unavailable")

    logger.debug("litellm_call", model_key=model_key, prompt_hash=_prompt_hash(messages))
    response: Any = await asyncio.wait_for(
        acompletion(model=MODEL_MAP[model_key], messages=messages, timeout=timeout),
        timeout=timeout,
    )
    content = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    tokens = int(getattr(usage, "total_tokens", 0) or 0)
    return ModelResponse(content=content, tokens=tokens, model=model_key)


async def count_tokens(model_key: str, messages: list[dict[str, str]]) -> int:
    """Count tokens for a set of messages.

    Args:
        model_key: Logical model key to resolve through MODEL_MAP.
        messages: Chat messages to count.

    Returns:
        Integer token count, using a rough fallback if LiteLLM counting fails.

    Cost/quality target:
        Free local accounting helper for pruning and route cost visibility.
    """
    if model_key not in MODEL_MAP:
        raise ValueError(f"Unknown model key: {model_key}")
    try:
        if token_counter is None:
            raise RuntimeError("token_counter unavailable")
        value = token_counter(model=MODEL_MAP[model_key], messages=messages)
        return int(value)
    except Exception:
        return max(1, len(str(messages)) // 4)
