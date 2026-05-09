import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from app.eval.datasets import DOMAINS, ensure_datasets, load_all_datasets
from app.eval.judge import judge_response
from app.lib.embeddings import embed_text
from app.lib.metrics import get_metrics, reset_metrics
from app.models.schemas import ChatMessage, ChatRequest
from app.pipeline import run_pipeline
from app.routers.admin import _NODES_STORE
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
    previous_percent = os.environ.get("NM_AUTO_ROUTE_GROQ_PERCENT")
    previous_prefix = os.environ.get("ROUTE_MODEL_PREFIX")
    os.environ["ROUTE_MODEL_PREFIX"] = "mock"
    if name == "sovereign_only":
        os.environ["NM_AUTO_ROUTE_GROQ_PERCENT"] = "0"
    elif name == "groq_only":
        os.environ["NM_AUTO_ROUTE_GROQ_PERCENT"] = "100"
    else:
        os.environ["NM_AUTO_ROUTE_GROQ_PERCENT"] = os.getenv("NM_AUTO_ROUTE_GROQ_PERCENT", "20")

    eval_redis = EvalRedis()
    eval_qdrant = EvalQdrant()
    cache_stage_module.get_redis_client = lambda: eval_redis
    cache_stage_module.get_qdrant_client = lambda: eval_qdrant
    _NODES_STORE["eval-node"] = {
        "node_id": "eval-node",
        "name": "eval-node",
        "location": "local",
        "model_versions": ["llama3.3:70b-instruct-q4_K_M"],
        "last_seen_at": "2999-01-01T00:00:00+00:00",
    }

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
    if previous_percent is None:
        os.environ.pop("NM_AUTO_ROUTE_GROQ_PERCENT", None)
    else:
        os.environ["NM_AUTO_ROUTE_GROQ_PERCENT"] = previous_percent
    if previous_prefix is None:
        os.environ.pop("ROUTE_MODEL_PREFIX", None)
    else:
        os.environ["ROUTE_MODEL_PREFIX"] = previous_prefix

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
    parser.add_argument("--output", type=Path, default=Path("docs/eval-results-beta-baseline.md"))
    args = parser.parse_args()

    ensure_datasets()
    prompts = load_all_datasets()
    configs = ["sovereign_only", "groq_only", "auto_routed"]
    await reset_metrics()
    results = [await run_config(config, prompts, args.limit) for config in configs]
    metrics = await get_metrics()

    payload = {
        "domains": DOMAINS,
        "total_prompts": len(prompts),
        "results": results,
        "metrics": metrics,
    }
    text = "# Beta Baseline Eval Results\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n"
    if args.output:
        args.output.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
