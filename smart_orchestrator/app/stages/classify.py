from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

from app.lib.metrics import record_classify
from app.models.schemas import ClassifyResult, PipelineContext

try:
    from litellm import acompletion
except Exception:  # pragma: no cover - dependency is installed in normal runtime
    acompletion = None  # type: ignore[assignment]


DOMAIN_KEYWORDS = {
    "code": {"code", "python", "javascript", "bug", "function", "sql", "api", "debug", "refactor"},
    "creative": {"story", "poem", "brand", "ad", "creative", "campaign", "voice", "script"},
    "factual": {"who", "what", "when", "where", "fact", "source", "latest", "current", "news"},
    "reasoning": {"why", "analyze", "compare", "strategy", "tradeoff", "reason", "plan"},
    "math": {"calculate", "solve", "equation", "proof", "probability", "integral", "sum"},
}

CLASSIFY_SYSTEM_PROMPT = (
    "You are a query classifier for an AI routing system. Classify the user query into exactly one "
    "domain from: [code, creative, factual, reasoning, math, chat]. Also classify complexity as one "
    "of: [simple, medium, complex]. Mark sensitive=true only if the query contains PII, medical, "
    "legal, or financial advice. Respond with valid JSON only: {\"domain\": \"...\", "
    "\"complexity\": \"...\", \"sensitive\": false}"
)

logger = logging.getLogger(__name__)


def _prompt_hash(prompt: str) -> str:
    """Hash prompt text for safe logs.

    Args:
        prompt: User query text to hash locally.

    Returns:
        First 16 hex chars of SHA-256 digest.

    Cost/quality target:
        Avoid logging prompt bodies while preserving debuggability.
    """

    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def _estimate_expected_tokens(prompt: str) -> int:
    """Estimate output token budget for legacy route compatibility.

    Args:
        prompt: User prompt.

    Returns:
        Estimated output token count.

    Cost/quality target:
        Zero-cost metadata for mocked downstream stages.
    """

    return max(128, min(2048, len(prompt.split()) * 4))


def _mock_classify(prompt: str, tokens_used: int = 0) -> ClassifyResult:
    """Classify a prompt with the Sprint 1 heuristic.

    Args:
        prompt: User prompt.
        tokens_used: Token count to attach, usually 0 for mock mode.

    Returns:
        ClassifyResult with domain, complexity, sensitivity, confidence, and token metadata.

    Cost/quality target:
        Zero-cost CI fallback and offline development classifier.
    """

    lowered = prompt.lower()
    scores = {
        domain: sum(1 for keyword in keywords if keyword in lowered)
        for domain, keywords in DOMAIN_KEYWORDS.items()
    }
    domain = max(scores, key=scores.get)
    if scores[domain] == 0:
        domain = "chat"

    word_count = len(lowered.split())
    if word_count < 20:
        complexity = "simple"
    elif word_count < 160:
        complexity = "medium"
    else:
        complexity = "complex"

    sensitive = any(
        term in lowered
        for term in [
            "ssn",
            "password",
            "credit card",
            "medical",
            "diagnosis",
            "legal advice",
            "financial advice",
            "bank account",
        ]
    )

    return ClassifyResult(
        domain=domain,
        complexity=complexity,
        sensitive=sensitive,
        confidence=0.85,
        tokens_used=tokens_used,
        expected_output_tokens=_estimate_expected_tokens(prompt),
    )


def _default_fallback(prompt: str) -> ClassifyResult:
    """Return the fixed safe fallback required for LiteLLM failures.

    Args:
        prompt: User prompt, used only for expected output token estimation.

    Returns:
        Default chat/simple non-sensitive classification with zero tokens.

    Cost/quality target:
        Zero-cost failure path; avoids breaking the pipeline when classifier output is invalid.
    """

    return ClassifyResult(
        domain="chat",
        complexity="simple",
        sensitive=False,
        confidence=0.85,
        tokens_used=0,
        expected_output_tokens=_estimate_expected_tokens(prompt),
    )


def _extract_tokens(response: Any) -> int:
    """Extract token usage from a LiteLLM response.

    Args:
        response: LiteLLM completion response object or dict.

    Returns:
        Total tokens used, or 0 when unavailable.

    Cost/quality target:
        Accurate classify accounting where provider metadata exists.
    """

    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return int(usage.get("total_tokens") or usage.get("completion_tokens") or 0)
    return int(getattr(usage, "total_tokens", 0) or getattr(usage, "completion_tokens", 0) or 0)


def _extract_content(response: Any) -> str:
    """Extract message content from a LiteLLM response.

    Args:
        response: LiteLLM completion response object or dict.

    Returns:
        Message content string.

    Cost/quality target:
        Keep classifier resilient across mocked dicts and LiteLLM objects.
    """

    if isinstance(response, dict):
        return response["choices"][0]["message"]["content"]
    return response.choices[0].message.content


async def _call_litellm_classifier(prompt: str) -> tuple[str, int]:
    """Call LiteLLM for classification.

    Args:
        prompt: User prompt.

    Returns:
        JSON content and token usage.

    Cost/quality target:
        Classify call costs ~200 tokens, target <250 tokens per call.
    """

    if acompletion is None:
        raise RuntimeError("LiteLLM is not available")
    response = await acompletion(
        model=os.getenv("CLASSIFY_MODEL", "llama-3.1-8b"),
        messages=[
            {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        timeout=8,
    )
    return _extract_content(response), _extract_tokens(response)


def _parse_classify_json(content: str, prompt: str, tokens_used: int) -> ClassifyResult:
    """Parse classifier JSON into a typed result.

    Args:
        content: Raw model content.
        prompt: User prompt for fallback-compatible expected token estimate.
        tokens_used: LiteLLM token usage.

    Returns:
        Parsed ClassifyResult.

    Cost/quality target:
        Strict JSON parsing prevents silent misroutes.
    """

    payload = json.loads(content)
    payload.setdefault("confidence", 0.85)
    payload.setdefault("tokens_used", tokens_used)
    payload["tokens_used"] = tokens_used
    payload["expected_output_tokens"] = _estimate_expected_tokens(prompt)
    return ClassifyResult.model_validate(payload)


async def classify_prompt(context: PipelineContext) -> PipelineContext:
    """Classify the prompt using LiteLLM with safe fallback.

    Args:
        context: Pipeline state containing request messages and metadata.

    Returns:
        The same context with a ClassifyResult attached.

    Cost/quality target:
        Classify call costs ~200 tokens, target <250 tokens per call.
    """
    prompt = context.prompt_text
    fallback = False
    if os.getenv("CLASSIFY_MODEL", "llama-3.1-8b") == "mock":
        result = _mock_classify(prompt)
    else:
        try:
            content, tokens_used = await _call_litellm_classifier(prompt)
            result = _parse_classify_json(content, prompt, tokens_used)
        except Exception as error:
            fallback = True
            logger.warning("classify_fallback prompt_hash=%s error=%s", _prompt_hash(prompt), type(error).__name__)
            result = _default_fallback(prompt)

    await record_classify(result.tokens_used, fallback=fallback)
    context.classification = result
    context.classify_tokens = result.tokens_used
    context.stage_events.append("classified")
    return context


async def classify_stage(context: PipelineContext) -> ClassifyResult:
    """Return prompt classification and store it on context.

    Args:
        context: Pipeline state with messages.

    Returns:
        Prompt classification.

    Cost/quality target:
        Test-friendly wrapper around the Sprint 1 heuristic classifier.
    """
    await classify_prompt(context)
    assert context.classification is not None
    return context.classification


run = classify_prompt
