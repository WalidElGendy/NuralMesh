"""Loop 2  Cache Curator: hourly job that scores and prunes the semantic cache."""
from __future__ import annotations

import json
import time
from typing import Any

from loops.shared.decisions_db import query_decisions

EVICTION_THRESHOLD = 0.30
BOOST_TTL_EXTENSION = 3600   # seconds to extend high-quality cache entries
CACHE_KEY_PREFIX = "semantic_cache:"
CURATION_LOG_PREFIX = "cache_curation_runs:"


def _freshness_score(verifier_score: float, hit_count: int, days_old: float) -> float:
    """
    freshness_score = verifier_score * hit_count / max(days_old, 1)
    Clipped to [0, 1].
    """
    raw = verifier_score * hit_count / max(days_old, 1.0)
    return min(1.0, raw)


async def run_cache_curator(redis, now: float | None = None) -> dict[str, Any]:
    """
    Main entry point for Loop 2.
    - Reads decisions from last hour
    - For each cache entry referenced, recomputes freshness score
    - Evicts entries below threshold; extends TTL on strong entries
    - Logs run summary to Redis hash

    Returns a summary dict.
    """
    now = now or time.time()
    hour_ago_ms = int((now - 3600) * 1000)

    decisions = query_decisions(redis, since_ms=hour_ago_ms)
    cache_hits = [d for d in decisions if d.cache_hit]

    # Build hit_count map per prompt_hash
    hit_counts: dict[str, int] = {}
    verifier_scores: dict[str, float] = {}
    for d in cache_hits:
        h = d.prompt_hash
        hit_counts[h] = hit_counts.get(h, 0) + 1
        verifier_scores[h] = max(verifier_scores.get(h, 0.0), d.verifier_score)

    evicted = 0
    extended = 0

    # Scan known cache keys
    cursor = 0
    while True:
        cursor, keys = redis.scan(cursor, match=f"{CACHE_KEY_PREFIX}*", count=100)
        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            prompt_hash = key_str.replace(CACHE_KEY_PREFIX, "")

            ttl = redis.ttl(key)
            if ttl < 0:
                continue  # Already expired or no TTL

            days_old = max(0.0, (3600 - ttl) / 86400)  # rough estimate
            vs = verifier_scores.get(prompt_hash, 0.5)
            hc = hit_counts.get(prompt_hash, 1)
            score = _freshness_score(vs, hc, days_old)

            if score < EVICTION_THRESHOLD:
                redis.delete(key)
                evicted += 1
            elif score > 0.7:
                redis.expire(key, ttl + BOOST_TTL_EXTENSION)
                extended += 1

        if cursor == 0:
            break

    summary = {
        "run_at": now,
        "decisions_examined": len(decisions),
        "cache_hits_examined": len(cache_hits),
        "evicted": evicted,
        "extended": extended,
    }

    # Log run
    run_key = f"{CURATION_LOG_PREFIX}{int(now)}"
    redis.hset(run_key, mapping={k: str(v) for k, v in summary.items()})
    redis.expire(run_key, 86400 * 30)  # Keep 30 days of run logs

    return summary
