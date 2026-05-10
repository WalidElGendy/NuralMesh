from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class GroqUsageRecord:
    timestamp: datetime
    user_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int


GROQ_USAGE_LOG: list[GroqUsageRecord] = []


async def log_groq_usage(
    *,
    user_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    db_pool: object | None = None,
) -> GroqUsageRecord:
    """Record platform-paid Groq usage; optionally mirror to Postgres."""

    record = GroqUsageRecord(
        timestamp=datetime.now(timezone.utc),
        user_id=user_id,
        model=model,
        prompt_tokens=max(0, prompt_tokens),
        completion_tokens=max(0, completion_tokens),
    )
    GROQ_USAGE_LOG.append(record)

    if db_pool is not None:
        await db_pool.execute(
            """
            INSERT INTO groq_usage (timestamp, user_id, model, prompt_tokens, completion_tokens)
            VALUES ($1, $2, $3, $4, $5)
            """,
            record.timestamp,
            record.user_id,
            record.model,
            record.prompt_tokens,
            record.completion_tokens,
        )

    return record
