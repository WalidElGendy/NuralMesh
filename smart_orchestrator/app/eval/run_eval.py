import argparse
import asyncio
import json
from pathlib import Path

from app.eval.datasets import DOMAINS, ensure_datasets, load_all_datasets
from app.eval.judge import judge_response
from app.models.schemas import ChatMessage, ChatRequest
from app.pipeline import run_pipeline


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
    total_cost = 0.0
    wins = 0
    cache_hits = 0
    escalations = 0

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
            cache_hit = False
            escalation = 0

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
    results = [await run_config(config, prompts, args.limit) for config in configs]

    payload = {
        "domains": DOMAINS,
        "total_prompts": len(prompts),
        "results": results,
    }
    text = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
