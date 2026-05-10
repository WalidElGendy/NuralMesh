from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.lib.groq_usage import log_groq_usage


DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


@dataclass(frozen=True)
class GroqCompletion:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class GroqClient:
    """Thin async wrapper around the Groq SDK."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.model = model or os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
        self._client = None

    def _sdk_client(self):
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is required for Groq routing")
        if self._client is None:
            try:
                from groq import AsyncGroq
            except Exception as exc:  # pragma: no cover - SDK installed in production image
                raise RuntimeError("groq Python SDK is unavailable") from exc
            self._client = AsyncGroq(api_key=self.api_key)
        return self._client

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        user_id: str,
    ) -> AsyncIterator[str]:
        """Yield streamed text chunks and let Sprint C consume token deltas."""

        stream = await self._sdk_client().chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            delta = getattr(chunk.choices[0].delta, "content", None) if chunk.choices else None
            if delta:
                yield delta

    async def complete_chat(
        self,
        messages: list[dict[str, str]],
        *,
        user_id: str,
    ) -> GroqCompletion:
        """Collect a streaming Groq response and log platform-paid token usage."""

        start = time.perf_counter()
        content_parts: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        stream = await self._sdk_client().chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or prompt_tokens)
                completion_tokens = int(
                    getattr(usage, "completion_tokens", 0) or completion_tokens
                )
            if chunk.choices:
                delta = getattr(chunk.choices[0].delta, "content", None)
                if delta:
                    content_parts.append(delta)

        if prompt_tokens == 0:
            prompt_tokens = max(1, len(str(messages)) // 4)
        content = "".join(content_parts)
        if completion_tokens == 0:
            completion_tokens = max(1, len(content) // 4)
        completion = GroqCompletion(
            content=content,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
        await log_groq_usage(
            user_id=user_id,
            model=completion.model,
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
        )
        return completion


groq_client = GroqClient()
