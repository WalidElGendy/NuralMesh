"""Stage 3: prune long conversation history with Mistral summarization."""

from __future__ import annotations

import os

from app.config import PRUNE_MODEL, PRUNE_MODEL_PREFIX, PRUNE_THRESHOLD
from app.lib.litellm_client import call_model, count_tokens
from app.lib.logger import get_logger
from app.lib.metrics import record_prune
from app.lib.telemetry import tracer
from app.models.schemas import ChatMessage, PipelineContext, PruneResult, StageEvent

logger = get_logger(__name__)

SUMMARY_SYSTEM_PROMPT = (
    "You are a conversation summarizer. Summarize the following conversation history concisely "
    "in 3-5 sentences, preserving key facts, decisions, and context that would be needed to "
    "continue the conversation."
)


def _as_dicts(messages: list[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


def _as_messages(history: list[dict[str, str]]) -> list[ChatMessage]:
    return [ChatMessage(role=turn["role"], content=turn["content"]) for turn in history]


def _prompt_hash(history: list[dict[str, str]]) -> str:
    import hashlib

    joined = "\n".join(f"{turn['role']}:{turn['content']}" for turn in history)
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


async def prune_conversation(history: list[dict[str, str]]) -> PruneResult:
    """Prune conversation history when token count exceeds threshold.

    Args:
        history: Conversation turns as role/content dictionaries.

    Returns:
        PruneResult with original or summarized history and token savings.

    Cost/quality target:
        Mistral pruning costs one local summarization call only for >2000-token
        histories; target is meaningful token savings before routing.
    """
    if not history:
        return PruneResult(history=[], was_pruned=False, original_tokens=0)

    original_tokens = await count_tokens(PRUNE_MODEL, history)
    if original_tokens <= PRUNE_THRESHOLD or len(history) <= 2:
        return PruneResult(history=history, was_pruned=False, original_tokens=original_tokens)

    last_two = history[-2:]
    old_turns = history[:-2]
    if os.environ.get("PRUNE_MODEL_PREFIX", "live") == "mock":
        summary = f"[MOCK SUMMARY: {len(history)} turns condensed]"
    else:
        formatted_history = "\n".join(
            f"{turn['role'].title()}: {turn['content']}" for turn in old_turns
        )
        try:
            model_response = await call_model(
                PRUNE_MODEL,
                [
                    {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": formatted_history},
                ],
                timeout=15,
            )
            summary = model_response.content
        except Exception as error:
            logger.warning(
                "prune fallback prompt_hash=%s error=%s",
                _prompt_hash(history),
                type(error).__name__,
            )
            return PruneResult(history=history, was_pruned=False, original_tokens=original_tokens)

    pruned_history = [
        {"role": "system", "content": f"[Summary of earlier conversation: {summary}]"},
        *last_two,
    ]
    pruned_tokens = await count_tokens(PRUNE_MODEL, pruned_history)
    result = PruneResult(
        history=pruned_history,
        was_pruned=True,
        original_tokens=original_tokens,
        pruned_tokens=pruned_tokens,
        tokens_saved=max(original_tokens - pruned_tokens, 0),
    )
    await record_prune(result.was_pruned, result.tokens_saved)
    return result


async def prune_history(ctx: PipelineContext) -> PipelineContext:
    """Summarize old turns when conversation history exceeds 2000 tokens.

    Args:
        ctx: Pipeline state after cache lookup.

    Returns:
        Context with pruned messages in ``ctx.working_messages`` when needed.

    Cost/quality target:
        Avoid expensive context windows while preserving recent turns and memory.
    """

    with tracer.start_as_current_span("prune") as span:
        if not ctx.working_messages:
            ctx.working_messages = list(ctx.messages)
        result = await prune_conversation(_as_dicts(ctx.working_messages))
        span.set_attribute("prune.was_pruned", result.was_pruned)
        span.set_attribute("prune.original_tokens", result.original_tokens)
        span.set_attribute("prune.tokens_saved", result.tokens_saved)
        ctx.prune_result = result
        ctx.prune_tokens_saved = result.tokens_saved
        if not result.was_pruned:
            ctx.stage_events.append(StageEvent(stage="prune", message="history within token budget"))
            return ctx

        ctx.working_messages = _as_messages(result.history)
        ctx.stage_events.append(
            StageEvent(
                stage="prune",
                message="summarized old turns",
                metadata={
                    "original_tokens": result.original_tokens,
                    "pruned_tokens": result.pruned_tokens,
                    "tokens_saved": result.tokens_saved,
                },
            )
        )
        return ctx


async def prune_stage(ctx: PipelineContext) -> PruneResult:
    """Run pruning and return the PruneResult for tests.

    Args:
        ctx: Pipeline context with working messages.

    Returns:
        PruneResult with history and token savings.

    Cost/quality target:
        Exposes pruning accounting while pipeline uses prune_history mutation.
    """

    await prune_history(ctx)
    return ctx.prune_result


run = prune_history
