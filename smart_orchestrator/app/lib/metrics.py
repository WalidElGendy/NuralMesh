from __future__ import annotations

import asyncio


_LOCK = asyncio.Lock()
_COUNTERS = {
    "cache_hits_redis": 0,
    "cache_hits_qdrant": 0,
    "cache_misses": 0,
    "classify_tokens_total": 0,
    "classify_fallbacks": 0,
    "tokens_saved_total": 0,
    "route_escalations_total": 0,
    "route_local_hits": 0,
    "route_frontier_hits": 0,
    "prune_activations": 0,
    "prune_tokens_saved_total": 0,
}


async def reset_metrics() -> None:
    """Reset in-memory counters for deterministic tests.

    Args:
        None.

    Returns:
        None.

    Cost/quality target:
        Zero-cost test helper; production metrics reset on process restart in Sprint 2.
    """
    async with _LOCK:
        for key in _COUNTERS:
            _COUNTERS[key] = 0


async def record_cache_hit(source: str, tokens_saved: int) -> None:
    """Record a cache hit or miss.

    Args:
        source: One of redis, qdrant, or miss.
        tokens_saved: Estimated route tokens avoided by the hit.

    Returns:
        None.

    Cost/quality target:
        Tracks Sprint 2 token-savings target without external metrics dependencies.
    """
    async with _LOCK:
        if source == "redis":
            _COUNTERS["cache_hits_redis"] += 1
        elif source == "qdrant":
            _COUNTERS["cache_hits_qdrant"] += 1
        else:
            _COUNTERS["cache_misses"] += 1
        _COUNTERS["tokens_saved_total"] += max(tokens_saved, 0)


async def record_cache_miss() -> None:
    """Record a cache miss.

    Args:
        None.

    Returns:
        None.

    Cost/quality target:
        Separates miss accounting from hit paths while keeping metrics dependency-free.
    """
    await record_cache_hit("miss", 0)


async def record_classify(tokens_used: int, fallback: bool) -> None:
    """Record classifier token usage and fallback count.

    Args:
        tokens_used: Tokens reported by LiteLLM, zero for mocked/fallback calls.
        fallback: Whether classification used fallback behavior.

    Returns:
        None.

    Cost/quality target:
        Keeps classifier overhead visible; target <250 tokens per classify call.
    """
    async with _LOCK:
        _COUNTERS["classify_tokens_total"] += max(tokens_used, 0)
        if fallback:
            _COUNTERS["classify_fallbacks"] += 1


async def record_route(escalation_count: int, model_used: str) -> None:
    """Record route cascade outcome.

    Args:
        escalation_count: Number of failed/low-confidence rungs before success.
        model_used: Final model key selected by the route stage.

    Returns:
        None.

    Cost/quality target:
        Tracks whether confidence gating keeps most traffic on local models.
    """
    frontier = {"claude-sonnet", "gemini-2.5-pro", "deepseek-v3"}
    async with _LOCK:
        _COUNTERS["route_escalations_total"] += max(escalation_count, 0)
        if escalation_count == 0 and model_used not in frontier:
            _COUNTERS["route_local_hits"] += 1
        if model_used in frontier:
            _COUNTERS["route_frontier_hits"] += 1


async def record_prune(was_pruned: bool, tokens_saved: int) -> None:
    """Record context pruning savings.

    Args:
        was_pruned: Whether summarization was applied.
        tokens_saved: Original token count minus pruned token count.

    Returns:
        None.

    Cost/quality target:
        Measures prompt budget saved before route calls.
    """
    async with _LOCK:
        if was_pruned:
            _COUNTERS["prune_activations"] += 1
            _COUNTERS["prune_tokens_saved_total"] += max(tokens_saved, 0)


async def get_metrics() -> dict[str, float | int]:
    """Return current in-memory Sprint 2 metrics.

    Args:
        None.

    Returns:
        Metrics dict with cache hit rate and estimated USD savings.

    Cost/quality target:
        Exposes actionable counters without Prometheus/OpenTelemetry until later sprints.
    """
    async with _LOCK:
        counters = dict(_COUNTERS)

    hits = counters["cache_hits_redis"] + counters["cache_hits_qdrant"]
    lookups = hits + counters["cache_misses"]
    hit_rate = hits / lookups if lookups else 0.0
    savings = counters["tokens_saved_total"] / 1000 * 0.003
    return {
        "cache_hit_rate": round(hit_rate, 4),
        "cache_hits_redis": counters["cache_hits_redis"],
        "cache_hits_qdrant": counters["cache_hits_qdrant"],
        "cache_misses": counters["cache_misses"],
        "classify_tokens_total": counters["classify_tokens_total"],
        "classify_fallbacks": counters["classify_fallbacks"],
        "estimated_cost_savings_usd": round(savings, 6),
        "route_escalations_total": counters["route_escalations_total"],
        "route_local_hits": counters["route_local_hits"],
        "route_frontier_hits": counters["route_frontier_hits"],
        "prune_activations": counters["prune_activations"],
        "prune_tokens_saved_total": counters["prune_tokens_saved_total"],
    }
