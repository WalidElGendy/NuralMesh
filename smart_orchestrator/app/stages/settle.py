"""Stage 7: settle job records, provider compute units, costs, and cache."""

from __future__ import annotations

from app.models.ledger import ledger
from app.models.schemas import PipelineContext
from app.stages.cache import write_cache


async def settle(ctx: PipelineContext) -> PipelineContext:
    """Persist final accounting records and cache verified safe answers.

    Args:
        ctx: Pipeline context with final answer, providers, and verification.

    Returns:
        Context with ledger records written and optional cache updated.

    Cost/quality target:
        Keep settlement deterministic in Sprint 1 while preserving the records
        real Postgres tables will receive later.
    """
    if not ctx.final_answer:
        raise ValueError("Cannot settle without a final answer")

    if ctx.cost_usd == 0:
        ctx.cost_usd = sum(response.cost_usd for response in ctx.providers_touched)
    if ctx.providers_paid == 0:
        ctx.providers_paid = sum(response.provider_paid_usd for response in ctx.providers_touched)

    await ledger.write_settlement(ctx)

    # Cache write-back happens after the mocked verifier clears the answer.
    if ctx.cache_allowed and ctx.verifier_verdict and ctx.verifier_verdict.pass_ and not ctx.low_confidence:
        await write_cache(ctx)

    ctx.add_event("settle.complete")
    return ctx


run = settle
settle_job = settle
