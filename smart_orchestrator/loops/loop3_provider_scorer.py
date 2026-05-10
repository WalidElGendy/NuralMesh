"""Loop 3  Provider Scorer: daily job that computes EWMA reputation per provider."""
from __future__ import annotations

import json
import time
from typing import Any

from loops.shared.decisions_db import query_decisions
from loops.shared.artifact_store import load_policy, save_policy

EWMA_ALPHA = 0.3   # weight for new observation (0.3 = ~3-day half-life for daily runs)
MIN_REPUTATION = 0.50
MAX_REPUTATION = 1.00
AUDIT_FRACTION = 0.01


def _compute_provider_score(
    verifier_scores: list[float],
    refusal_count: int,
    total_count: int,
    current_reputation: float,
) -> float:
    """
    Compute new EWMA reputation.
    raw_score = mean(verifier_scores) * (1 - refusal_rate)
    new_rep = alpha * raw_score + (1-alpha) * current_rep
    """
    if not verifier_scores or total_count == 0:
        return current_reputation

    mean_vs = sum(verifier_scores) / len(verifier_scores)
    refusal_rate = refusal_count / total_count
    raw = mean_vs * (1.0 - refusal_rate)
    new_rep = EWMA_ALPHA * raw + (1.0 - EWMA_ALPHA) * current_reputation
    return max(MIN_REPUTATION, min(MAX_REPUTATION, round(new_rep, 4)))


def _reputation_to_multiplier(reputation: float) -> float:
    """Quality-adjusted rate multiplier for provider payout."""
    if reputation >= 0.95:
        return 1.20
    if reputation >= 0.90:
        return 1.10
    if reputation >= 0.80:
        return 1.00
    if reputation >= 0.70:
        return 0.90
    return 0.80


async def run_provider_scorer(redis, now: float | None = None) -> dict[str, Any]:
    """
    Main entry point for Loop 3.
    - Reads last 24h decisions
    - For each provider node in providers_paid, aggregates verifier scores
    - Computes EWMA reputation
    - Writes updated provider_reputation.json via artifact_store
    Returns summary dict.
    """
    now = now or time.time()
    day_ago_ms = int((now - 86400) * 1000)

    decisions = query_decisions(redis, since_ms=day_ago_ms)

    # Aggregate per provider
    provider_verifier: dict[str, list[float]] = {}
    provider_refusals: dict[str, int] = {}
    provider_total: dict[str, int] = {}

    for d in decisions:
        for prov in (d.providers_paid or []):
            pid = prov.get("node_id", "") if isinstance(prov, dict) else str(prov)
            if not pid:
                continue
            provider_total[pid] = provider_total.get(pid, 0) + 1
            vs = d.verifier_score
            if vs < 0.1:  # treat near-zero as refusal
                provider_refusals[pid] = provider_refusals.get(pid, 0) + 1
            else:
                provider_verifier.setdefault(pid, []).append(vs)

    # Load current policy
    policy = load_policy("provider_reputation")
    providers = policy.get("providers", {})

    updated_providers: dict[str, dict] = {}
    for pid in set(list(provider_total.keys()) + list(providers.keys())):
        current_rep = providers.get(pid, {}).get("reputation", policy.get("default_reputation", 0.80))
        vscores = provider_verifier.get(pid, [])
        refusals = provider_refusals.get(pid, 0)
        total = provider_total.get(pid, 0)
        new_rep = _compute_provider_score(vscores, refusals, total, current_rep)
        updated_providers[pid] = {
            "reputation": new_rep,
            "rate_multiplier": _reputation_to_multiplier(new_rep),
            "last_scored_at": now,
            "samples": total,
        }

    policy["providers"] = updated_providers
    save_policy("provider_reputation", policy)

    return {
        "run_at": now,
        "decisions_examined": len(decisions),
        "providers_scored": len(updated_providers),
    }
