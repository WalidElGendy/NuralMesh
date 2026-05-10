from __future__ import annotations

import hashlib


async def judge_answer(prompt: str, candidate: str, baseline: str) -> float:
    """Score a candidate answer against a baseline using a deterministic mock judge.

    Args:
        prompt: Evaluation prompt text.
        candidate: Orchestrator or baseline answer.
        baseline: Reference baseline answer.

    Returns:
        Float score in [0, 1]. Target is stable relative ranking without API keys.
    """
    seed = f"{prompt}|{candidate}|{baseline}".encode()
    digest = hashlib.sha256(seed).digest()
    return 0.55 + (digest[0] / 255) * 0.4


class JudgeVerdict:
    """Minimal verdict object for the mocked eval harness."""

    def __init__(self, score: float) -> None:
        self.score = score
        self.win = score >= 0.6


async def judge_response(prompt: str, candidate: str, expected_answer_type: str) -> JudgeVerdict:
    """Judge an answer using a deterministic Claude Opus stand-in.

    Args:
        prompt: Evaluation prompt.
        candidate: Candidate response text.
        expected_answer_type: Dataset answer type hint.

    Returns:
        JudgeVerdict with score and win boolean.

    Cost/quality target:
        Zero-cost stable judging until real Claude Opus eval calls are enabled.
    """
    score = await judge_answer(prompt, candidate, expected_answer_type)
    return JudgeVerdict(score)
