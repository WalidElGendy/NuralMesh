from __future__ import annotations

import math
from typing import Any

from app.lib.embeddings import embed_prompt
from app.models.schemas import CachedAnswer, PipelineContext, StageEvent


_CACHE: dict[str, list[CachedAnswer]] = {}


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


async def semantic_cache_lookup(context: PipelineContext) -> StageEvent:
    """Look up a verified semantic cache answer.

    Args:
        context: Pipeline state after classification.

    Returns:
        Stage event describing hit, miss, or skip behavior.

    Cost/quality target:
        Skip unsafe/fresh prompts; target 0 marginal LLM cost on >=0.95 hits.
    """
    if context.classification is None:
        raise ValueError("classification is required before cache lookup")

    classification = context.classification
    if classification.sensitivity != "none" or classification.needs_freshness:
        context.cache_checked = True
        return StageEvent(stage="cache", status="skipped", detail="fresh or sensitive prompt")

    embedding = await embed_prompt(context.latest_user_prompt)
    context.embedding = embedding
    collection = f"nm_cache_{classification.domain}"

    best: tuple[float, CachedAnswer] | None = None
    for cached in _CACHE.get(collection, []):
        similarity = _cosine_similarity(embedding, cached.embedding)
        if similarity >= 0.95 and (best is None or similarity > best[0]):
            best = (similarity, cached)

    context.cache_checked = True
    if best is None:
        return StageEvent(stage="cache", status="miss", detail=collection)

    similarity, cached_answer = best
    context.cache_hit = cached_answer
    context.cached_answer = cached_answer
    context.final_answer = cached_answer.answer
    context.low_confidence = False
    context.metadata["cache_similarity"] = similarity
    return StageEvent(stage="cache", status="hit", detail=f"{collection} similarity={similarity:.3f}")


async def semantic_cache_stage(context: PipelineContext) -> PipelineContext:
    """Run semantic cache lookup and return context.

    Args:
        context: Pipeline state after classification.

    Returns:
        Updated context with cache metadata.

    Cost/quality target:
        Test-friendly wrapper over the Qdrant mock with zero external cost.
    """

    await semantic_cache_lookup(context)
    return context


async def check_semantic_cache(context: PipelineContext) -> bool:
    """Return whether semantic cache produced an answer.

    Args:
        context: Pipeline state after classification.

    Returns:
        True when cache hit exists, otherwise False.

    Cost/quality target:
        Lets pipeline skip expensive stages on high-confidence safe hits.
    """

    await semantic_cache_lookup(context)
    return context.cached_answer is not None


async def write_cache(context: PipelineContext) -> None:
    """Store a verified final answer in the in-memory Qdrant mock.

    Args:
        context: Completed pipeline context.

    Returns:
        None.

    Cost/quality target:
        Populate semantic cache only for verified non-sensitive answers.
    """
    if not context.classification or not context.final_answer or not context.embedding:
        return
    if context.classification.sensitivity != "none" or context.classification.needs_freshness:
        return
    if not context.verifier_verdict or not context.verifier_verdict.pass_:
        return

    collection = f"nm_cache_{context.classification.domain}"
    _CACHE.setdefault(collection, []).append(
        CachedAnswer(
            prompt=context.latest_user_prompt,
            answer=context.final_answer,
            domain=context.classification.domain,
            embedding=context.embedding,
            metadata={"job_id": context.job_id},
        )
    )


store_cached_answer = write_cache
