"""Decision logger DB layer  write/query decisions table via Redis stream."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


STREAM_KEY = "decisions:stream"
MAX_STREAM_LEN = 100_000  # Trim stream to this length


@dataclass
class Decision:
    """One inference decision record."""
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    prompt_hash: str = ""
    cache_hit: bool = False
    ladder_used: str = ""
    rungs_attempted: list = field(default_factory=list)
    final_model: str = ""
    verifier_score: float = 0.0
    user_feedback: str = "none"   # thumbs_up | thumbs_down | none
    latency_ms: int = 0
    cost_usd: float = 0.0
    providers_paid: list = field(default_factory=list)

    def to_redis_fields(self) -> dict[str, str]:
        d = asdict(self)
        return {k: json.dumps(v) if isinstance(v, (list, dict, bool)) else str(v) for k, v in d.items()}

    @classmethod
    def from_redis_fields(cls, fields: dict) -> "Decision":
        def _dec(v: Any) -> str:
            return v.decode() if isinstance(v, bytes) else str(v)

        def _parse(k: str, v: Any) -> Any:
            raw = _dec(v)
            if k in ("rungs_attempted", "providers_paid"):
                try:
                    return json.loads(raw)
                except Exception:
                    return []
            if k == "cache_hit":
                return raw.lower() in ("true", "1")
            if k in ("verifier_score", "cost_usd"):
                return float(raw)
            if k in ("latency_ms",):
                return int(raw)
            if k == "timestamp":
                return float(raw)
            return raw

        # Decode byte keys from Redis
        str_fields = {(k.decode() if isinstance(k, bytes) else k): v for k, v in fields.items()}
        data = {k: _parse(k, v) for k, v in str_fields.items() if k in cls.__dataclass_fields__}
        return cls(**data)


def write_decision(decision: Decision, redis) -> str:
    """Write a Decision to the Redis stream. Returns the stream entry ID."""
    entry_id = redis.xadd(
        STREAM_KEY,
        decision.to_redis_fields(),
        maxlen=MAX_STREAM_LEN,
        approximate=True,
    )
    return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)


def query_decisions(
    redis,
    since_ms: Optional[int] = None,
    count: int = 1000,
    filter_feedback: Optional[str] = None,
) -> list[Decision]:
    """Read recent decisions from the stream."""
    start = f"{since_ms}-0" if since_ms else "0-0"
    entries = redis.xrange(STREAM_KEY, min=start, count=count)
    decisions = []
    for _entry_id, fields in entries:
        try:
            d = Decision.from_redis_fields(fields)
            if filter_feedback and d.user_feedback != filter_feedback:
                continue
            decisions.append(d)
        except Exception:
            pass
    return decisions


def hash_prompt(prompt: str) -> str:
    """SHA-256 hash of prompt  never store raw text."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]
