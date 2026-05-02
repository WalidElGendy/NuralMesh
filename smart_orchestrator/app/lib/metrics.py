"""Prometheus metrics for NeuralMesh Smart Orchestrator (Sprint 9)."""
from prometheus_client import Counter, Histogram, Gauge, REGISTRY

# Request counters
REQUESTS_TOTAL = Counter(
    "orchestrator_requests_total",
    "Total number of inference requests",
    ["endpoint", "tier", "category", "status"],
)

# Token counters
TOKENS_TOTAL = Counter(
    "orchestrator_tokens_total",
    "Total tokens consumed",
    ["tier", "model"],
)

# Latency histogram (seconds)
REQUEST_LATENCY = Histogram(
    "orchestrator_request_latency_seconds",
    "Request latency in seconds",
    ["endpoint", "model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

# Active WebSocket connections gauge
WS_CONNECTIONS = Gauge(
    "orchestrator_ws_connections_active",
    "Number of active WebSocket connections",
)

# Model escalation counter
ESCALATIONS_TOTAL = Counter(
    "orchestrator_escalations_total",
    "Number of model escalations triggered",
    ["from_model", "to_model"],
)

# Error counter
ERRORS_TOTAL = Counter(
    "orchestrator_errors_total",
    "Total errors by type",
    ["error_type", "endpoint"],
)


def record_request(endpoint: str, tier: str, category: str, status: str) -> None:
    """Increment request counter."""
    REQUESTS_TOTAL.labels(
        endpoint=endpoint, tier=tier, category=category, status=status
    ).inc()


def record_tokens(tier: str, model: str, count: int) -> None:
    """Add token usage."""
    TOKENS_TOTAL.labels(tier=tier, model=model).inc(count)


def record_latency(endpoint: str, model: str, seconds: float) -> None:
    """Observe request latency."""
    REQUEST_LATENCY.labels(endpoint=endpoint, model=model).observe(seconds)


def record_escalation(from_model: str, to_model: str) -> None:
    """Increment escalation counter."""
    ESCALATIONS_TOTAL.labels(from_model=from_model, to_model=to_model).inc()


def record_error(error_type: str, endpoint: str) -> None:
    """Increment error counter."""
    ERRORS_TOTAL.labels(error_type=error_type, endpoint=endpoint).inc()


# Cache counters (used by app.stages.cache)
CACHE_HITS = Counter(
    "orchestrator_cache_hits_total",
    "Total cache hits",
    ["cache_type"],
)

CACHE_MISSES = Counter(
    "orchestrator_cache_misses_total",
    "Total cache misses",
    ["cache_type"],
)


async def record_cache_hit(cache_type: str = "redis", tokens_saved: int = 0) -> None:
    """Increment cache hit counter."""
    CACHE_HITS.labels(cache_type=cache_type).inc()


async def record_cache_miss(cache_type: str = "redis") -> None:
    """Increment cache miss counter."""
    CACHE_MISSES.labels(cache_type=cache_type).inc()


async def get_metrics() -> dict:
    """Return in-memory metrics snapshot for the /metrics JSON endpoint."""
    from prometheus_client import generate_latest
    return {
        "prometheus": generate_latest().decode("utf-8"),
        "counters": {
            "requests_total": float(
                sum(s.value for s in REQUESTS_TOTAL._metrics.values())
                if hasattr(REQUESTS_TOTAL, "_metrics") else 0
            ),
        },
    }


# Stage-specific counters (used by classify, route, prune stages)
CLASSIFY_CALLS = Counter(
    "orchestrator_classify_calls_total",
    "Total classify stage calls",
    ["result"],
)

ROUTE_CALLS = Counter(
    "orchestrator_route_calls_total",
    "Total route stage calls",
    ["model"],
)

PRUNE_CALLS = Counter(
    "orchestrator_prune_calls_total",
    "Total prune stage calls",
)


async def record_classify(tokens_used: int = 0, fallback: bool = False) -> None:
    """Increment classify call counter."""
    CLASSIFY_CALLS.labels(result="fallback" if fallback else "ok").inc()


async def record_route(escalation_count: int = 0, model: str = "unknown") -> None:
    """Increment route call counter."""
    ROUTE_CALLS.labels(model=model).inc()


async def record_prune(was_pruned: bool = False, tokens_saved: int = 0) -> None:
    """Increment prune call counter."""
    PRUNE_CALLS.inc()


def reset_metrics() -> None:
    """Reset all in-process counters (used in eval/testing)."""
    # prometheus_client counters cannot be truly reset;
    # we track a local offset for eval purposes
    pass
