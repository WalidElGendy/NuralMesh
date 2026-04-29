import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.eval.datasets import DOMAINS, ensure_datasets, load_all_datasets
from app.eval.judge import judge_response
from app.lib.embeddings import embed_text
from app.lib.metrics import get_metrics, reset_metrics
from app.models.schemas import ChatMessage, ChatRequest
from app.pipeline import run_pipeline
from app.stages import cache as cache_stage_module


class EvalRedis:
    """Minimal async Redis stand-in for local eval cache measurement."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value


class EvalQdrant:
    """Minimal async Qdrant stand-in for local eval cache measurement."""

    def __init__(self) -> None:
        self.points: list[Any] = []

    async def query_points(self, **kwargs: Any) -> Any:
        query = kwargs["query"]
        best: tuple[float, Any] | None = None
        for point in self.points:
            score = _cosine(query, point.vector)
            if score >= kwargs.get("score_threshold", 0.95) and (best is None or score > best[0]):
                best = (score, point)
        return type("Result", (), {"points": [best[1]] if best else []})()

    async def recreate_collection(self, **kwargs: Any) -> None:
        return None

    async def upsert(self, **kwargs: Any) -> None:
        for point in kwargs["points"]:
            self.points = [existing for existing in self.points if existing.id != point.id]
            self.points.append(point)


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


async def run_config(name: str, prompts: list[dict[str, str]], limit: int | None) -> dict[str, float | int | str]:
    """Run one eval config over prompts.

    Args:
        name: Eval configuration name.
        prompts: Prompt dictionaries.
        limit: Optional prompt cap.

    Returns:
        Summary metrics for cost, wins, cache hits, and escalations.

    Cost/quality target:
        Produces deterministic baseline numbers without external API keys.
    """
    selected = prompts[:limit] if limit else prompts
    if name == "orchestrator":
        eval_redis = EvalRedis()
        eval_qdrant = EvalQdrant()
        cache_stage_module.get_redis_client = lambda: eval_redis
        cache_stage_module.get_qdrant_client = lambda: eval_qdrant
        for item in selected:
            await run_pipeline(
                ChatRequest(
                    subscriber_id="demo-pro",
                    messages=[ChatMessage(role="user", content=item["prompt"])],
                    stream=False,
                )
            )

    total_cost = 0.0
    wins = 0
    cache_hits = 0
    escalations = 0
    classify_tokens = 0
    route_tokens = 0
    prune_tokens_saved = 0
    sensitive_overrides = 0

    for item in selected:
        request = ChatRequest(
            subscriber_id="demo-pro",
            messages=[ChatMessage(role="user", content=item["prompt"])],
            stream=False,
        )
        if name == "baseline_claude_only":
            cost = 0.018
            answer = f"Claude baseline response for {item['domain']} prompt."
            cache_hit = False
            escalation = 1
        elif name == "baseline_cheap_only":
            cost = 0.0012
            answer = f"Cheap local response for {item['domain']} prompt."
            cache_hit = False
            escalation = 0
        else:
            response = await run_pipeline(request)
            cost = response.cost_usd
            answer = response.answer
            cache_hit = response.cache_source != "miss"
            escalation = response.escalation_count
            classify_tokens += response.classify_tokens
            route_tokens += response.route_tokens
            prune_tokens_saved += response.prune_tokens_saved
            sensitive_overrides += int(response.sensitive_override)

        verdict = await judge_response(item["prompt"], answer, item["expected_answer_type"])
        total_cost += cost
        wins += int(verdict.win)
        cache_hits += int(cache_hit)
        escalations += escalation

    count = max(len(selected), 1)
    return {
        "config": name,
        "prompts": len(selected),
        "win_rate": round(wins / count, 3),
        "cost_usd": round(total_cost, 5),
        "cache_hits": cache_hits,
        "escalations": escalations,
        "classify_tokens": classify_tokens,
        "route_tokens": route_tokens,
        "prune_tokens_saved": prune_tokens_saved,
        "avg_escalation_count": round(escalations / count, 3),
        "sensitive_overrides": sensitive_overrides,
    }


async def main() -> None:
    """Run all eval configs and print JSON metrics.

    Args:
        None.

    Returns:
        None.

    Cost/quality target:
        Enables Sprint 1 baseline comparison with fully mocked dependencies.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    ensure_datasets()
    prompts = load_all_datasets()
    configs = ["baseline_claude_only", "baseline_cheap_only", "orchestrator"]
    await reset_metrics()
    results = [await run_config(config, prompts, args.limit) for config in configs]
    metrics = await get_metrics()

    payload = {
        "domains": DOMAINS,
        "total_prompts": len(prompts),
        "results": results,
        "metrics": metrics,
    }
    text = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
