from __future__ import annotations

import logging
from app.models.ledger import ledger
from app.models.schemas import PipelineContext
from app.stages.cache import write_cache
from app.stages.cache import get_redis_client
from app.lib.provider_earnings import accrue_earnings
from loops.shared.artifact_store import get_provider_reputation, reputation_to_multiplier

logger = logging.getLogger(__name__)


async def settle(ctx: PipelineContext) -> PipelineContext:
    """
    Settle stage: record cost and provider payout, write to cache if eligible.

    Quality-Adjusted Pricing (Sprint 16):
    - Reads provider reputation from app/policies/provider_reputation.json
    - Applies rate multiplier to each provider's raw payout
    - rep >= 0.95 -> 1.20x, >= 0.90 -> 1.10x, >= 0.80 -> 1.00x,
      >= 0.70 -> 0.90x, else -> 0.80x
    - Multiplied payout is stored in ctx.providers_paid
    - Keep settlement deterministic in Sprint 1 while preserving the records
      real Postgres tables will receive later.
    """
    if not ctx.final_answer:
        raise ValueError("Cannot settle without a final answer")

    if ctx.cost_usd == 0:
        ctx.cost_usd = sum(response.cost_usd for response in ctx.providers_touched)

    # Quality-Adjusted Pricing: apply reputation multiplier to each payout
    if ctx.providers_paid == 0:
        adjusted_total = 0.0
        for response in ctx.providers_touched:
            rep = get_provider_reputation(response.provider_id)
            multiplier = reputation_to_multiplier(rep)
            adjusted_payout = response.provider_paid_usd * multiplier
            adjusted_total += adjusted_payout
            logger.debug(
                "QAP: provider=%s rep=%.3f multiplier=%.2fx "
                "raw=%.6f adjusted=%.6f",
                response.provider_id,
                rep,
                multiplier,
                response.provider_paid_usd,
                adjusted_payout,
            )
        ctx.providers_paid = adjusted_total

    redis_client = None
    try:
        redis_client = get_redis_client()
        for response in ctx.providers_touched:
            if response.external or not response.served_by or not response.served_by.startswith("node:"):
                continue
            tokens = response.prompt_tokens + response.completion_tokens
            await accrue_earnings(redis_client, response.provider_id, tokens, response.model)
    except Exception as exc:
        logger.warning("provider earnings accrual skipped: %s", exc)
    finally:
        if redis_client is not None:
            close = getattr(redis_client, "aclose", None)
            if close is not None:
                await close()

    await ledger.write_settlement(ctx)

    # Cache write-back happens after the mocked verifier clears the answer.
    if ctx.cache_allowed and ctx.verifier_verdict and ctx.verifier_verdict.pass_ and not ctx.low_confidence:
        await write_cache(ctx)

    ctx.add_event("settle.complete")
    return ctx


run = settle
settle_job = settle
