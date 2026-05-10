from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import Distance, PointStruct, VectorParams
from redis.exceptions import ConnectionError as RedisConnectionError

from app.lib.embeddings import embed_text
from app.lib.logger import get_logger
from app.lib.metrics import record_cache_hit, record_cache_miss
from app.lib.telemetry import tracer
from app.models.schemas import CachedAnswer, CacheResult, PipelineContext, StageEvent


logger = get_logger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "prompt_cache"
REDIS_TTL_SECONDS = 300
SEMANTIC_THRESHOLD = 0.95


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _short_hash(prompt: str) -> str:
    return _prompt_hash(prompt)[:16]


def _redis_key(domain: str, prompt: str) -> str:
    # Cache key includes domain to avoid cross-domain collisions.
    return f"cache:exact:{domain}:{_prompt_hash(prompt)}"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _safe_to_read_cache(context: PipelineContext) -> bool:
    classification = context.classification
    if classification is None:
        return False
    return (
        not classification.sensitive
        and classification.domain != "fresh"
        and classification.confidence >= 0.7
    )


def _safe_to_write_cache(context: PipelineContext) -> bool:
    classification = context.classification
    answer = context.final_answer or context.answer
    # Invalidation rules:
    # - Never cache sensitive=True.
    # - Never cache classification confidence < 0.7.
    # - Never cache answers that contain "[HALLUCINATION DETECTED]".
    # - Redis TTL is 300s; Qdrant has no TTL and is permanent until manual flush.
    return bool(
        classification
        and not classification.sensitive
        and classification.confidence >= 0.7
        and answer
        and len(answer) > 20
        and "[HALLUCINATION DETECTED]" not in answer
        and (context.verifier_verdict is None or context.verifier_verdict.pass_)
    )


def get_redis_client() -> redis.Redis:
    """Create an async Redis client.

    Args:
        None.

    Returns:
        Redis asyncio client configured from REDIS_URL.

    Cost/quality target:
        Hot exact-match cache should return in single-digit milliseconds.
    """
    return redis.from_url(REDIS_URL, decode_responses=True)


def get_qdrant_client() -> AsyncQdrantClient:
    """Create an async Qdrant client.

    Args:
        None.

    Returns:
        AsyncQdrantClient configured from QDRANT_URL.

    Cost/quality target:
        Semantic cache lookup target is ~10-30ms when Qdrant is reachable.
    """
    return AsyncQdrantClient(url=QDRANT_URL)


async def _lookup_redis(context: PipelineContext, client: Any | None = None) -> CacheResult | None:
    key = _redis_key(context.classification.domain, context.latest_user_prompt)  # type: ignore[union-attr]
    client = client or get_redis_client()
    should_close = not hasattr(client, "mock_calls")
    try:
        cached = await client.get(key)
    except RedisConnectionError as error:
        logger.warning("redis cache unavailable prompt_hash=%s error=%s", _short_hash(context.latest_user_prompt), error)
        return None
    except Exception as error:
        logger.warning("redis cache skipped prompt_hash=%s error=%s", _short_hash(context.latest_user_prompt), error)
        return None
    finally:
        close = getattr(client, "aclose", None) if should_close else None
        if close is not None:
            await close()

    if not cached:
        return None
    payload = json.loads(cached)
    tokens_saved = int(
        payload.get("tokens_saved", payload.get("tokens", _estimate_tokens(payload.get("answer", ""))))
    )
    await record_cache_hit("redis", tokens_saved)
    return CacheResult(
        hit=True,
        answer=payload["answer"],
        tokens_saved=tokens_saved,
        source="redis",
        latency_ms=0.0,
    )


async def _lookup_qdrant(context: PipelineContext, client: Any | None = None) -> CacheResult | None:
    prompt = context.latest_user_prompt
    embedding = await embed_text(prompt)
    context.embedding = embedding
    client = client or get_qdrant_client()
    should_close = not hasattr(client, "mock_calls")
    try:
        if hasattr(client, "query_points"):
            result = await client.query_points(
                collection_name=COLLECTION_NAME,
                query=embedding,
                limit=1,
                score_threshold=SEMANTIC_THRESHOLD,
            )
            hits = getattr(result, "points", [])
        else:
            hits = await client.search(
                collection_name=COLLECTION_NAME,
                query_vector=embedding,
                limit=1,
                score_threshold=SEMANTIC_THRESHOLD,
            )
    except Exception as error:
        logger.warning("qdrant cache unavailable prompt_hash=%s error=%s", _short_hash(prompt), error)
        return None
    finally:
        close = getattr(client, "close", None) if should_close else None
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    if not hits:
        return None
    payload = hits[0].payload or {}
    answer = payload.get("answer")
    if not answer:
        return None
    tokens_saved = int(payload.get("tokens", _estimate_tokens(answer)))
    await record_cache_hit("qdrant", tokens_saved)
    return CacheResult(
        hit=True,
        answer=answer,
        tokens_saved=tokens_saved,
        source="qdrant",
        latency_ms=0.0,
    )


async def semantic_cache_lookup(
    context: PipelineContext,
    redis_client: Any | None = None,
    qdrant_client: Any | None = None,
) -> CacheResult:
    """Look up an answer in Redis exact cache and Qdrant semantic cache.

    Args:
        context: Pipeline state containing prompt and ClassifyResult.

    Returns:
        CacheResult indicating redis/qdrant hit or miss with latency.

    Cost/quality target:
        Achieve token-cost savings through safe cache hits while never crashing
        the pipeline if Redis or Qdrant is unavailable.
    """
    with tracer.start_as_current_span("cache.read") as span:
        started = time.perf_counter()
        if context.classification is None:
            raise ValueError("classification is required before cache lookup")
        if not _safe_to_read_cache(context):
            await record_cache_miss()
            result = CacheResult(hit=False, source="miss", latency_ms=(time.perf_counter() - started) * 1000)
            context.cache_result = result
            context.cache_checked = True
            span.set_attribute("cache.hit", False)
            span.set_attribute("cache.layer", "miss")
            return result

        result = await _lookup_redis(context, redis_client)
        if result is None:
            result = await _lookup_qdrant(context, qdrant_client)

        if result is None:
            await record_cache_miss()
            result = CacheResult(hit=False, source="miss", latency_ms=(time.perf_counter() - started) * 1000)
        else:
            result.latency_ms = (time.perf_counter() - started) * 1000
            cached = CachedAnswer(
                prompt=context.latest_user_prompt,
                answer=result.answer or "",
                domain=context.classification.domain,
                embedding=context.embedding or [],
                metadata={"source": result.source},
            )
            context.cache_hit = cached
            context.cached_answer = cached
            context.final_answer = result.answer

        context.cache_result = result
        context.cache_source = result.source
        context.cache_checked = True
        span.set_attribute("cache.hit", result.hit)
        span.set_attribute("cache.layer", result.source)
        return result


async def semantic_cache_stage(
    context: PipelineContext,
    redis_client: Any | None = None,
    qdrant_client: Any | None = None,
) -> PipelineContext:
    """Run the two-layer semantic cache stage and mutate context.

    Args:
        context: Pipeline state after classification.

    Returns:
        Updated context with CacheResult and cached answer when found.

    Cost/quality target:
        Skip downstream route tokens on exact or high-confidence semantic hits.
    """
    await semantic_cache_lookup(context, redis_client=redis_client, qdrant_client=qdrant_client)
    return context


async def cache_stage(
    context: PipelineContext,
    redis_client: Any | None = None,
    qdrant_client: Any | None = None,
) -> CacheResult:
    """Run cache lookup and return the Sprint 2 cache result for tests.

    Args:
        context: Pipeline context with prompt and classification.
        redis_client: Optional mocked Redis client.
        qdrant_client: Optional mocked Qdrant client.

    Returns:
        CacheResult from Redis, Qdrant, or miss path.

    Cost/quality target:
        Allows deterministic cache unit tests while preserving pipeline context mutation.
    """

    return await semantic_cache_lookup(
        context,
        redis_client=redis_client,
        qdrant_client=qdrant_client,
    )


async def check_semantic_cache(context: PipelineContext) -> bool:
    """Return whether cache produced an answer.

    Args:
        context: Pipeline state after classification.

    Returns:
        True when Redis or Qdrant returned a cache hit.

    Cost/quality target:
        Boolean compatibility wrapper for the pipeline.
    """
    result = await semantic_cache_lookup(context)
    return result.hit


async def write_cache(
    context: PipelineContext,
    redis_client: Any | None = None,
    qdrant_client: Any | None = None,
) -> None:
    """Write a verified answer to Redis and Qdrant.

    Args:
        context: Completed pipeline context after verification and settlement.
        redis_client: Optional mocked Redis client for tests.
        qdrant_client: Optional mocked Qdrant client for tests.

    Returns:
        None.

    Cost/quality target:
        Populate hot and semantic caches only for safe, verified answers.
    """
    if not _safe_to_write_cache(context):
        return

    prompt = context.latest_user_prompt
    answer = context.final_answer or context.answer
    prompt_hash = _prompt_hash(prompt)
    tokens = _estimate_tokens(answer)
    payload = {
        "prompt_hash": prompt_hash,
        "answer": answer,
        "domain": context.classification.domain,  # type: ignore[union-attr]
        "tokens": tokens,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    redis_client = redis_client or get_redis_client()
    close_redis = not hasattr(redis_client, "mock_calls")
    try:
        await redis_client.setex(
            _redis_key(context.classification.domain, prompt),  # type: ignore[union-attr]
            REDIS_TTL_SECONDS,
            json.dumps(payload),
        )
    except Exception as error:
        logger.warning("redis cache write failed prompt_hash=%s error=%s", _short_hash(prompt), error)
    finally:
        close = getattr(redis_client, "aclose", None) if close_redis else None
        if close is not None:
            await close()

    qdrant_client = qdrant_client or get_qdrant_client()
    close_qdrant = not hasattr(qdrant_client, "mock_calls")
    try:
        embedding = context.embedding or await embed_text(prompt)
        context.embedding = embedding
        if hasattr(qdrant_client, "recreate_collection"):
            await qdrant_client.recreate_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=len(embedding), distance=Distance.COSINE),
            )
        await qdrant_client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=prompt_hash,
                    vector=embedding,
                    payload=payload,
                )
            ],
        )
    except Exception as error:
        logger.warning("qdrant cache write failed prompt_hash=%s error=%s", _short_hash(prompt), error)
    finally:
        close = getattr(qdrant_client, "close", None) if close_qdrant else None
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


store_cached_answer = write_cache
