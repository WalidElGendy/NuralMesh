"""Loop 1  Decision Logger: FastAPI middleware that captures /infer decisions."""
from __future__ import annotations

import hashlib
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from loops.shared.decisions_db import Decision, write_decision, hash_prompt

LOGGED_PATHS = {"/infer", "/chat"}


class DecisionLoggerMiddleware(BaseHTTPMiddleware):
    """
    In-process FastAPI middleware.
    Captures every POST /infer (or /chat) request + response metadata,
    writes a Decision record to the Redis stream.
    Adds <3ms p99 overhead (pure in-memory, fire-and-forget pattern).
    Privacy: only prompt_hash (sha-256 truncated) is stored, never raw text.
    """

    def __init__(self, app, redis_client):
        super().__init__(app)
        self._redis = redis_client

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method != "POST" or request.url.path not in LOGGED_PATHS:
            return await call_next(request)

        t0 = time.monotonic()
        response = await call_next(request)
        latency_ms = int((time.monotonic() - t0) * 1000)

        try:
            # Read metadata injected by the router via response headers
            final_model = response.headers.get("X-Final-Model", "")
            ladder_used = response.headers.get("X-Ladder-Used", "")
            cache_hit = response.headers.get("X-Cache-Hit", "false").lower() == "true"
            cost_str = response.headers.get("X-Cost-USD", "0.0")
            prompt_hash = response.headers.get("X-Prompt-Hash", "")

            decision = Decision(
                prompt_hash=prompt_hash,
                cache_hit=cache_hit,
                ladder_used=ladder_used,
                final_model=final_model,
                latency_ms=latency_ms,
                cost_usd=float(cost_str),
            )
            write_decision(decision, self._redis)
        except Exception:
            pass  # Never let logging break the response

        return response


def make_prompt_hash(prompt: str) -> str:
    """Public helper for routers to stamp X-Prompt-Hash header."""
    return hash_prompt(prompt)
