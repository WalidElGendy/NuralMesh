"""Stage 5: confidence-gated cascade routing through domain ladders."""

from __future__ import annotations

import hashlib
import os
import re

from app.config import CONFIDENCE_THRESHOLD
from app.lib.litellm_client import call_model
from app.lib.logger import get_logger
from app.lib.metrics import record_route
from app.lib.telemetry import tracer
from app.models.schemas import MeshResponse, PipelineContext, RouteAttempt, RouteResult


LADDERS: dict[str, list[str]] = {
    "code": ["qwen-coder-7b", "deepseek-v3", "claude-sonnet"],
    "creative": ["llama-3.1-8b", "claude-sonnet"],
    "factual": ["llama-3.1-8b", "gemini-2.5-pro"],
    "reasoning": ["llama-3.1-8b", "deepseek-v3", "claude-sonnet"],
    "math": ["qwen-coder-7b", "deepseek-v3", "gemini-2.5-pro"],
    "chat": ["llama-3.1-8b"],
}

CONFIDENCE_SUFFIX = (
    "\n\nAfter your response, on a new line write exactly: Confidence: [0.00-1.00] "
    "where the number reflects your certainty about the answer quality."
)
CONFIDENCE_RE = re.compile(r"Confidence:\s*(0\.\d+|1\.0+)", re.IGNORECASE)
FRONTIER_MODELS = {"claude-sonnet", "gemini-2.5-pro"}
logger = get_logger(__name__)


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def _extract_confidence(content: str) -> tuple[str, float]:
    match = CONFIDENCE_RE.search(content)
    if not match:
        return content.strip(), 0.75
    confidence = float(match.group(1))
    stripped = CONFIDENCE_RE.sub("", content).strip()
    return stripped, confidence


def _mock_route_result(domain: str) -> RouteResult:
    return RouteResult(
        model_used="llama-3.1-8b",
        response=f"[MOCK] Sprint 3 mocked response for domain={domain}",
        confidence=0.85,
        tokens_used=0,
        escalation_count=0,
        ladder_domain=domain,
        sensitive_override=False,
    )


async def _call_route_model(model_key: str, prompt: str, system: str | None) -> MeshResponse:
    """Call one routed model via LiteLLM.

    Args:
        model_key: Logical model key from the ladder.
        prompt: Prompt text.
        system: Optional system instruction.

    Returns:
        MeshResponse from LiteLLM client.

    Cost/quality target:
        Local model call ~500 tokens, escalation to frontier ~2000 tokens, target
        <1000 average tokens per route call across eval set.
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system + CONFIDENCE_SUFFIX})
    else:
        messages.append({"role": "system", "content": CONFIDENCE_SUFFIX.strip()})
    messages.append({"role": "user", "content": prompt})
    return await call_model(model_key, messages, timeout=30)


async def route_request(context: PipelineContext) -> PipelineContext:
    """Execute confidence-gated cascade routing.

    Args:
        context: Pipeline context after prune/compress with ClassifyResult.

    Returns:
        Context containing RouteResult and selected MeshResponse.

    Cost/quality target:
        Local model call ~500 tokens, escalation to frontier ~2000 tokens, target
        <1000 average tokens per route call across the eval set.
    """
    assert context.classification is not None
    domain = context.classification.domain
    prompt = context.compressed_prompt or context.prompt
    sensitive_override = context.classification.sensitive
    ladder = ["claude-sonnet"] if sensitive_override else LADDERS[domain]
    if sensitive_override:
        logger.info("routing sensitive query to claude-sonnet prompt_hash=%s", _prompt_hash(prompt))

    with tracer.start_as_current_span("route") as route_span:
        route_span.set_attribute("route.ladder_domain", domain)
        route_span.set_attribute("route.sensitive_override", sensitive_override)

        if os.environ.get("ROUTE_MODEL_PREFIX", "live") == "mock":
            route_result = _mock_route_result(domain)
            route_span.set_attribute("route.escalation_count", route_result.escalation_count)
            context.route_result = route_result
            context.selected_response = MeshResponse(
                provider_id="mock-route",
                model=route_result.model_used,
                content=route_result.response,
                confidence=route_result.confidence,
                self_critique="Sprint 3 route mock.",
                latency_ms=0,
                proof_of_compute="mock-route-proof",
                cost_usd=0.0,
                provider_paid_usd=0.0,
            )
            context.final_answer = route_result.response
            context.route_tokens = 0
            await record_route(0, route_result.model_used)
            return context

        last_error: Exception | None = None
        for index, model_key in enumerate(ladder):
            escalated = index > 0
            with tracer.start_as_current_span("route.attempt") as attempt_span:
                attempt_span.set_attribute("route.model", model_key)
                attempt_span.set_attribute("route.escalated", escalated)
                attempt_span.set_attribute("route.sensitive_override", sensitive_override)
                try:
                    raw = await _call_route_model(model_key, prompt, context.system)
                except Exception as error:
                    last_error = error
                    context.escalations += int(index < len(ladder) - 1)
                    attempt_span.record_exception(error)
                    continue

                answer, confidence = _extract_confidence(raw.content or raw.text or "")
                attempt_span.set_attribute("route.confidence", confidence)
                result = MeshResponse(
                    provider_id=f"litellm-{model_key}",
                    model=model_key,
                    content=answer,
                    confidence=confidence,
                    self_critique="Confidence extracted from model response footer.",
                    latency_ms=0,
                    proof_of_compute=f"litellm-route-{_prompt_hash(prompt)}-{model_key}",
                    cost_usd=0.0,
                    provider_paid_usd=0.0,
                    external=model_key in FRONTIER_MODELS,
                )
                context.providers_touched.append(result)
                context.provider_touches.append(result)
                context.route_attempts.append(
                    RouteAttempt(
                        model=model_key,
                        provider_id=result.provider_id,
                        confidence=result.confidence,
                        verifier_passed=False,
                    )
                )
                if confidence >= CONFIDENCE_THRESHOLD or index == len(ladder) - 1:
                    escalation_count = index
                    route_result = RouteResult(
                        model_used=model_key,
                        response=answer,
                        confidence=confidence,
                        tokens_used=raw.tokens,
                        escalation_count=escalation_count,
                        ladder_domain=domain,
                        sensitive_override=sensitive_override,
                    )
                    route_span.set_attribute("route.escalation_count", escalation_count)
                    context.route_result = route_result
                    context.selected_response = result
                    context.final_answer = answer
                    context.route_tokens = raw.tokens
                    context.escalations = escalation_count
                    await record_route(escalation_count, model_key)
                    return context
                context.escalations += 1

        logger.error("route fallback", prompt_hash=_prompt_hash(prompt), error=type(last_error).__name__)
        route_result = _mock_route_result(domain)
        route_result.model_used = "mock-fallback"
        route_result.escalation_count = max(len(ladder) - 1, 0)
        route_span.set_attribute("route.escalation_count", route_result.escalation_count)
        context.route_result = route_result
        context.selected_response = MeshResponse(
            provider_id="mock-route-fallback",
            model=route_result.model_used,
            content=route_result.response,
            confidence=route_result.confidence,
            self_critique="All route models failed; returned safe mock fallback.",
            latency_ms=0,
            proof_of_compute="mock-route-fallback-proof",
        )
        context.final_answer = route_result.response
        context.route_tokens = 0
        await record_route(route_result.escalation_count, route_result.model_used)
        return context


async def route_stage(context: PipelineContext) -> RouteResult:
    """Run routing and return the RouteResult for tests.

    Args:
        context: Pipeline context with classification and prompt.

    Returns:
        RouteResult selected by the cascade.

    Cost/quality target:
        Exposes route accounting while pipeline uses route_request mutation.
    """

    await route_request(context)
    assert context.route_result is not None
    return context.route_result


run = route_request
