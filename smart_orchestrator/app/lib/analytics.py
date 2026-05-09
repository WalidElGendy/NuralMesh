from __future__ import annotations

from typing import Any

import httpx

from app.config import POSTHOG_API_KEY, POSTHOG_HOST
from app.lib.logger import get_logger
from app.stages.cache import get_redis_client

logger = get_logger(__name__)


async def track_event(event: str, distinct_id: str, properties: dict[str, Any] | None = None) -> None:
    """Track beta launch events in Redis and optionally PostHog."""

    payload = {"event": event, "distinct_id": distinct_id, "properties": properties or {}}
    try:
        redis = get_redis_client()
        await redis.xadd("analytics:events", payload, maxlen=10000, approximate=True)
        await redis.aclose()
    except Exception as exc:
        logger.warning("analytics_redis_failed", event=event, error=str(exc))

    if not POSTHOG_API_KEY:
        return

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{POSTHOG_HOST.rstrip('/')}/capture/",
                json={**payload, "api_key": POSTHOG_API_KEY},
            )
    except Exception as exc:
        logger.warning("analytics_posthog_failed", event=event, error=str(exc))

