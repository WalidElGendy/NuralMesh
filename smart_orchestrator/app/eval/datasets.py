from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DOMAINS: tuple[str, ...] = ("code", "creative", "factual", "reasoning", "math", "chat")
COMPLEXITIES: tuple[str, ...] = ("simple", "medium", "hard", "medium", "simple")
DATASET_DIR = Path(__file__).parent / "datasets"


PROMPT_TEMPLATES: dict[str, list[str]] = {
    "code": [
        "Refactor a Python function that batches API calls with exponential backoff and explain tradeoffs.",
        "Design a TypeScript interface for a billing ledger with immutable adjustment entries.",
        "Find the bug in an async FastAPI handler that streams server-sent events under cancellation.",
        "Write SQL indexes for a job queue filtered by status, priority, and created_at.",
        "Explain how to test a Redis Streams consumer group for duplicate delivery.",
    ],
    "creative": [
        "Write a launch email for a developer tool that turns idle GPUs into inference capacity.",
        "Draft a concise product manifesto for decentralized AI infrastructure without crypto hype.",
        "Create five names for an observability dashboard showing Proof-of-Compute events.",
        "Rewrite a technical paragraph in a confident, premium SaaS voice.",
        "Produce a short founder note explaining USD payouts for GPU providers.",
    ],
    "factual": [
        "Compare the operational differences between centralized cloud GPUs and decentralized GPU networks.",
        "Explain why public API keys are different from service role keys in Supabase.",
        "Summarize the role of vector similarity thresholds in semantic caching.",
        "List common causes of hallucination in LLM outputs and mitigation strategies.",
        "Describe how PostgreSQL, Redis, and Qdrant serve different orchestration needs.",
    ],
    "reasoning": [
        "A job can run on three providers with different latency, cost, and confidence; choose the best route.",
        "Decide when to escalate from a local model to a frontier model given verifier uncertainty.",
        "Given competing constraints of cost, quality, and freshness, propose a routing policy.",
        "Analyze whether a cache hit should be served for a prompt containing confidential information.",
        "Reason about failure handling when proof verification fails after an otherwise good response.",
    ],
    "math": [
        "Compute the monthly gross margin if 10,000 requests cost $0.0008 each and revenue is $49.",
        "A provider completes 1,200 jobs at $0.006 per job; calculate payout and platform fee at 18%.",
        "Estimate cache savings if 22% of 80,000 requests avoid a $0.002 model call.",
        "Solve for break-even subscribers when fixed infrastructure costs are $2,400 and plan price is $49.",
        "Calculate weighted average latency across three providers with 120ms, 210ms, and 95ms latencies.",
    ],
    "chat": [
        "Explain NeuralMesh to a non-technical founder in four sentences.",
        "Help a GPU provider decide whether to list an RTX 4090 on the network.",
        "Answer a customer asking whether NeuralMesh uses crypto tokens.",
        "Suggest next steps for a startup migrating from OpenAI API to NeuralMesh.",
        "Explain why confidence and verification both matter for AI inference quality.",
    ],
}


def build_dataset_record(domain: str, index: int) -> dict[str, Any]:
    """Create one realistic eval record.

    Args:
        domain: Dataset domain.
        index: Zero-based prompt index.

    Returns:
        JSON-serializable prompt metadata.

    Cost/quality target:
        Keeps generated evals deterministic and broad enough for Sprint 1 comparisons.
    """
    template = PROMPT_TEMPLATES[domain][index % len(PROMPT_TEMPLATES[domain])]
    complexity = COMPLEXITIES[index % len(COMPLEXITIES)]
    return {
        "id": f"{domain}-{index + 1:03d}",
        "domain": domain,
        "complexity": complexity,
        "expected_answer_type": {
            "code": "implementation_or_debugging_guidance",
            "creative": "polished_marketing_copy",
            "factual": "grounded_explanation",
            "reasoning": "structured_decision",
            "math": "numeric_solution_with_work",
            "chat": "helpful_conversation",
        }[domain],
        "prompt": f"{template} Scenario #{index + 1}: include concrete constraints and a practical recommendation.",
    }


def ensure_datasets() -> list[Path]:
    """Generate 50 prompts per domain as JSONL files.

    Args:
        None.

    Returns:
        Paths to generated dataset files.

    Cost/quality target:
        Produces 300 deterministic, non-toy prompts without external dependencies.
    """
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for domain in DOMAINS:
        path = DATASET_DIR / f"{domain}.jsonl"
        with path.open("w", encoding="utf-8") as dataset_file:
            for index in range(50):
                dataset_file.write(json.dumps(build_dataset_record(domain, index)) + "\n")
        paths.append(path)
    return paths


def load_all_datasets() -> list[dict[str, Any]]:
    """Load every eval record, generating datasets if needed.

    Args:
        None.

    Returns:
        A list of dataset records.

    Cost/quality target:
        Gives the eval harness stable local inputs for baseline comparisons.
    """
    ensure_datasets()
    records: list[dict[str, Any]] = []
    for path in sorted(DATASET_DIR.glob("*.jsonl")):
        if path.name == ".gitkeep":
            continue
        with path.open("r", encoding="utf-8") as dataset_file:
            records.extend(json.loads(line) for line in dataset_file if line.strip())
    return records


if __name__ == "__main__":
    ensure_datasets()
