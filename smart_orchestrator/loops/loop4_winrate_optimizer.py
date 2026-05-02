"""
Loop 4  Win-Rate Optimizer (daily cron)
=========================================
Samples recent decisions from the decisions stream, evaluates them using an
LLM-as-judge approach, and updates the ladders.json policy artifact when
a new ladder configuration demonstrates a statistically significant win-rate
improvement over the current baseline.

North-star metric: Win-rate vs baseline (LLM-as-judge win rate vs. always-Sonnet).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loops.shared.artifact_store import (
    get_ladders,
    load_policy,
    save_policy,
    reputation_to_multiplier,
    get_provider_reputation,
)
from loops.shared.ab_gate import ABGate, ArtifactMetrics
from loops.shared.decisions_db import query_decisions

logger = logging.getLogger(__name__)

#  constants 
JUDGE_SAMPLE_SIZE = int(os.getenv("LOOP4_SAMPLE_SIZE", "200"))
MIN_SAMPLE_SIZE = 20          # refuse to run with fewer decisions
JUDGE_PROMPT_TEMPLATE = """You are evaluating the quality of an AI assistant response.

Task intent: {intent}
Model used: {model}
Response quality score: {score:.2f}

Rate whether this response is better than a baseline claude-sonnet response.
Reply with exactly one word: BETTER, SAME, or WORSE."""

BASELINE_MODEL = "claude-sonnet"


@dataclass
class WinRateResult:
    """Aggregated win-rate evaluation result for a ladder configuration."""

    intent: str
    total_evaluated: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    avg_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    costs: list[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        if self.total_evaluated == 0:
            return 0.0
        return self.wins / self.total_evaluated

    @property
    def cost_per_win(self) -> float:
        if self.wins == 0:
            return float("inf")
        return self.avg_cost_usd / self.win_rate

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "total_evaluated": self.total_evaluated,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "win_rate": round(self.win_rate, 4),
            "avg_cost_usd": round(self.avg_cost_usd, 6),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
        }


def judge_response(
    intent: str,
    model: str,
    score: float,
    *,
    rng: random.Random | None = None,
) -> str:
    """
    Simulated LLM-as-judge evaluation.

    In production this would call an LLM API; here we use a deterministic
    heuristic so the loop is testable without external API calls.

    Rules (mirroring real judge behavior):
    - If model == BASELINE_MODEL: always SAME
    - If score >= 0.85: BETTER (high quality non-baseline)
    - If score <= 0.50: WORSE  (low quality)
    - Otherwise: weighted random with score as BETTER probability
    """
    _rng = rng or random.Random()
    if model == BASELINE_MODEL:
        return "SAME"
    if score >= 0.85:
        return "BETTER"
    if score <= 0.50:
        return "WORSE"
    # weighted: higher score -> more likely BETTER
    roll = _rng.random()
    if roll < score:
        return "BETTER"
    return "WORSE"


async def evaluate_decisions(
    redis_client: Any,
    sample_size: int = JUDGE_SAMPLE_SIZE,
) -> dict[str, WinRateResult]:
    """
    Sample recent decisions and evaluate win-rate per intent category.

    Returns a dict mapping intent -> WinRateResult.
    """
    decisions = query_decisions(redis_client, count=sample_size)

    if len(decisions) < MIN_SAMPLE_SIZE:
        logger.warning(
            "Loop4: only %d decisions available (need %d), skipping",
            len(decisions),
            MIN_SAMPLE_SIZE,
        )
        return {}

    results: dict[str, WinRateResult] = {}
    rng = random.Random(42)  # deterministic for reproducibility

    for decision in decisions:
        intent = decision.ladder_used
        if intent not in results:
            results[intent] = WinRateResult(intent=intent)

        r = results[intent]
        verdict = judge_response(
            intent=intent,
            model=decision.final_model,
            score=decision.verifier_score,
            rng=rng,
        )

        r.total_evaluated += 1
        if verdict == "BETTER":
            r.wins += 1
        elif verdict == "WORSE":
            r.losses += 1
        else:
            r.ties += 1

        r.costs.append(decision.cost_usd)

    # Compute averages
    for r in results.values():
        if r.costs:
            r.avg_cost_usd = sum(r.costs) / len(r.costs)

    return results


def compute_composite_score(results: dict[str, WinRateResult]) -> float:
    """
    Compute composite score across all intent categories.

    Formula: weighted average win_rate, weighted by sample size.
    """
    total_weight = sum(r.total_evaluated for r in results.values())
    if total_weight == 0:
        return 0.0
    weighted_sum = sum(
        r.win_rate * r.total_evaluated for r in results.values()
    )
    return weighted_sum / total_weight


async def run(redis_client: Any) -> dict[str, Any]:
    """
    Main entry point for Loop 4.

    1. Sample recent decisions from Redis stream
    2. Evaluate win-rate per intent using LLM-as-judge
    3. Load current ladders artifact
    4. Compute composite score and compare via AB gate
    5. Promote if improved; write results to win_rate_history.json
    """
    logger.info("Loop4: starting win-rate optimization run")
    started_at = datetime.now(timezone.utc).isoformat()

    # Step 1+2: Evaluate decisions
    results = await evaluate_decisions(redis_client)
    if not results:
        return {
            "status": "skipped",
            "reason": "insufficient_decisions",
            "started_at": started_at,
        }

    composite = compute_composite_score(results)
    logger.info("Loop4: composite win-rate = %.4f", composite)

    # Step 3: Load current ladders
    current_ladders = get_ladders()

    # Step 4: Load previous metrics baseline
    history_policy = load_policy("win_rate_history")
    prev_composite = float(history_policy.get("last_composite", 0.0))
    prev_cost = float(history_policy.get("last_avg_cost_usd", 0.0))

    # Current cost = average across all results
    all_costs: list[float] = []
    for r in results.values():
        all_costs.extend(r.costs)
    current_cost = sum(all_costs) / len(all_costs) if all_costs else 0.0

    # Step 5: AB gate evaluation
    gate = ABGate()
    current_metrics = ArtifactMetrics(
        win_rate=composite,
        cost_per_1k=current_cost * 1000.0,
    )
    baseline_metrics = ArtifactMetrics(
        win_rate=prev_composite or composite * 0.98,  # seed: 2% below current
        cost_per_1k=(prev_cost or current_cost) * 1000.0,
    )
    promoted = gate.should_promote(current_metrics, baseline_metrics)

    outcome = {
        "status": "evaluated",
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "composite_win_rate": round(composite, 4),
        "prev_composite_win_rate": round(prev_composite, 4),
        "cost_regression": round(
            (current_cost - (prev_cost or current_cost)) / max(prev_cost or current_cost, 1e-9),
            4,
        ),
        "promoted": promoted,
        "intent_breakdown": {k: v.to_dict() for k, v in results.items()},
    }

    if promoted:
        logger.info(
            "Loop4: promoting ladders artifact (composite %.4f > prev %.4f)",
            composite,
            prev_composite,
        )
        # Write updated ladders (current ladders, now with confirmed win-rate backing)
        save_policy("ladders", {"ladders": current_ladders})

    # Always update win_rate_history
    history_policy["last_composite"] = round(composite, 4)
    history_policy["last_avg_cost_usd"] = round(current_cost, 6)
    history_policy["last_run"] = started_at
    history_policy["runs"] = history_policy.get("runs", 0) + 1
    save_policy("win_rate_history", history_policy)

    logger.info("Loop4: done  promoted=%s", promoted)
    return outcome


if __name__ == "__main__":  # pragma: no cover
    import fakeredis.aioredis as fakeredis

    async def _main() -> None:
        r = fakeredis.FakeRedis()
        result = await run(r)
        print(json.dumps(result, indent=2))

    asyncio.run(_main())
