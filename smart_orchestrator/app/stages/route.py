"""Stage 5: route requests through domain-specific model ladders."""

from __future__ import annotations

from app.lib.litellm_client import call_model
from app.lib.mesh_dispatch import dispatch_to_provider
from app.models.schemas import MeshResponse, PipelineContext, RouteAttempt
from app.stages.verify import verify_answer


LADDERS: dict[str, list[str]] = {
    "code": ["qwen-coder-7b", "deepseek-v3", "claude-sonnet"],
    "creative": ["llama-3.1-8b", "claude-sonnet"],
    "factual": ["llama-3.1-8b", "gemini-2.5-pro"],
    "reasoning": ["llama-3.1-8b", "deepseek-v3", "claude-sonnet"],
    "math": ["qwen-coder-7b", "deepseek-v3", "gemini-2.5-pro"],
    "chat": ["llama-3.1-8b"],
}

FRONTIER_MODELS = {"claude-sonnet", "gemini-2.5-pro", "deepseek-api"}


async def _call_model(model: str, prompt: str, context: PipelineContext) -> MeshResponse:
    """Call either mocked mesh-local models or LiteLLM frontier models.

    Args:
        model: Model identifier selected by the ladder.
        prompt: Current prompt after pruning/compression.
        system: Optional system prompt.

    Returns:
        Normalized model call result with confidence, proof, and cost metadata.

    Cost/quality target:
        Prefer mocked provider nodes first; use external frontier calls only at
        high rungs and only when relevant API keys exist.
    """
    if model in FRONTIER_MODELS:
        return await call_model(model, prompt, context)
    return await dispatch_to_provider(model, prompt, context.system)


async def route_request(context: PipelineContext) -> PipelineContext:
    """Execute the model cascade for the classified prompt domain.

    Args:
        context: Pipeline context after compression.

    Returns:
        Context containing selected result, verification, and escalation count.

    Cost/quality target:
        Start at cheapest viable rung; escalate on low confidence or verifier
        failure. Hard prompts jump directly to the top rung.
    """
    assert context.classification is not None
    ladder = LADDERS[context.classification.domain]
    start_index = len(ladder) - 1 if context.classification.complexity == "hard" else 0
    prompt = context.compressed_prompt or context.prompt

    for index, model in enumerate(ladder[start_index:], start=start_index):
        result = await _call_model(model, prompt, context)
        context.providers_touched.append(result)
        context.provider_touches.append(result)
        verdict = await verify_answer(context, result.content, result.model)
        context.verifier_verdict = verdict
        context.route_attempts.append(
            RouteAttempt(
                model=result.model,
                provider_id=result.provider_id,
                confidence=result.confidence,
                verifier_passed=verdict.pass_,
            )
        )

        is_top_rung = index == len(ladder) - 1
        if result.confidence >= 0.8 and verdict.pass_:
            context.selected_response = result
            context.final_answer = result.content
            context.low_confidence = False
            return context

        if is_top_rung:
            context.selected_response = result
            context.final_answer = result.content
            context.low_confidence = True
            return context

        context.escalations += 1

    return context


route_stage = route_request
run = route_request
