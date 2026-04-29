from __future__ import annotations

from app.lib.mesh_dispatch import dispatch_to_mesh
from app.models.schemas import Classification, PipelineContext


DOMAIN_KEYWORDS = {
    "code": {"code", "python", "javascript", "bug", "function", "sql", "api", "debug", "refactor"},
    "creative": {"story", "poem", "brand", "ad", "creative", "campaign", "voice", "script"},
    "factual": {"who", "what", "when", "where", "fact", "source", "latest", "current", "news"},
    "reasoning": {"why", "analyze", "compare", "strategy", "tradeoff", "reason", "plan"},
    "math": {"calculate", "solve", "equation", "proof", "probability", "integral", "sum"},
}


async def classify_prompt(context: PipelineContext) -> PipelineContext:
    """Classify the prompt using mocked mesh inference.

    Args:
        context: Pipeline state containing request messages and metadata.

    Returns:
        The same context with a Classification attached.

    Cost/quality target:
        Cheap local classifier; target <$0.0001 and stable routing labels.
    """
    prompt = context.prompt_text.lower()
    words = prompt.split()
    scores = {
        domain: sum(1 for keyword in keywords if keyword in prompt)
        for domain, keywords in DOMAIN_KEYWORDS.items()
    }
    domain = max(scores, key=scores.get)
    if scores[domain] == 0:
        domain = "chat"

    word_count = len(words)
    if word_count < 20:
        complexity = "trivial"
    elif word_count < 80:
        complexity = "simple"
    elif word_count < 220:
        complexity = "medium"
    else:
        complexity = "hard"

    needs_freshness = any(term in prompt for term in ["latest", "today", "current", "news", "2026"])
    sensitivity = "none"
    if any(term in prompt for term in ["ssn", "password", "credit card", "personal data"]):
        sensitivity = "pii"
    if any(term in prompt for term in ["confidential", "internal only", "nda"]):
        sensitivity = "confidential"

    await dispatch_to_mesh("llama-3.1-8b", context.prompt_text, domain="chat")
    context.classification = Classification(
        domain=domain,
        complexity=complexity,
        needs_freshness=needs_freshness,
        sensitivity=sensitivity,
        expected_output_tokens=max(128, min(2048, word_count * 4)),
    )
    context.stage_events.append("classified")
    return context


async def classify_stage(context: PipelineContext) -> Classification:
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
