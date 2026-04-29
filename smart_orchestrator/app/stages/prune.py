"""Stage 3: prune long conversation history with a mocked summarizer."""

from __future__ import annotations

from app.lib.mesh_dispatch import dispatch_to_provider
from app.models.schemas import ChatMessage, PipelineContext, StageEvent


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


async def prune_history(ctx: PipelineContext) -> PipelineContext:
    """Summarize old turns when conversation history exceeds 2000 tokens.

    Args:
        ctx: Pipeline state after cache lookup.

    Returns:
        Context with pruned messages in ``ctx.working_messages`` when needed.

    Cost/quality target:
        Avoid expensive context windows while preserving recent turns and memory.
    """

    total_tokens = sum(_estimate_tokens(message.content) for message in ctx.working_messages)
    if total_tokens <= 2000 or len(ctx.working_messages) <= 2:
        ctx.stage_events.append(StageEvent(stage="prune", message="history within token budget"))
        return ctx

    older_turns = ctx.working_messages[:-2]
    last_two = ctx.working_messages[-2:]
    summary_prompt = "\n".join(f"{turn.role}: {turn.content[:600]}" for turn in older_turns)
    summary = await dispatch_to_provider(
        model="mistral-7b",
        prompt=f"Summarize these conversation turns for memory:\n{summary_prompt}",
    )
    memory = ChatMessage(role="system", content=f"<memory>{summary.text}</memory>")
    ctx.working_messages = [memory, *last_two]
    ctx.stage_events.append(
        StageEvent(stage="prune", message="summarized old turns", metadata={"original_tokens": total_tokens})
    )
    return ctx


run = prune_history
