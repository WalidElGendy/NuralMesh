import asyncio
import os
import random
from typing import Any

from app.lib.mesh_dispatch import LOCAL_MODELS, dispatch_to_mesh
from app.models.schemas import MeshResponse, PipelineContext


FRONTIER_MODELS = {
    "claude-sonnet": "anthropic/claude-3-5-sonnet-20241022",
    "gemini-2.5-pro": "gemini/gemini-2.5-pro",
    "deepseek-api": "deepseek/deepseek-chat",
}


async def call_model(model: str, prompt: str, context: PipelineContext) -> MeshResponse:
    """Call a local mocked model or frontier LiteLLM provider.

    Args:
        model: Logical model name from route ladders.
        prompt: Prompt text for the model.
        context: Pipeline context used for job metadata and provider tracking.

    Returns:
        MeshResponse with response, confidence, cost, and provider metadata.

    Cost/quality target:
        Prefer mocked local mesh calls for zero-key Sprint 1 operation; use real
        LiteLLM only when the relevant provider API key exists.
    """
    if model in LOCAL_MODELS:
        return await dispatch_to_mesh(model, prompt, context)

    has_key = (
        (model == "claude-sonnet" and os.environ.get("ANTHROPIC_API_KEY"))
        or (model == "gemini-2.5-pro" and os.environ.get("GEMINI_API_KEY"))
        or (model == "deepseek-api" and os.environ.get("DEEPSEEK_API_KEY"))
        or (model.startswith("deepseek") and os.environ.get("DEEPSEEK_API_KEY"))
    )
    if not has_key:
        return await _mock_frontier_call(model, prompt, context)

    try:
        from litellm import acompletion

        response: Any = await acompletion(
            model=FRONTIER_MODELS.get(model, model),
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content
        return MeshResponse(
            model=model,
            provider_id=f"frontier-{model}",
            content=content,
            confidence=0.9,
            self_critique="Frontier provider response; confidence estimated high.",
            latency_ms=int(getattr(response, "_response_ms", 250) or 250),
            cost_usd=0.004,
            provider_paid_usd=0.0,
            proof_of_compute=f"frontier-api-{model}",
            external=True,
        )
    except Exception:
        return await _mock_frontier_call(model, prompt, context)


async def _mock_frontier_call(model: str, prompt: str, context: PipelineContext) -> MeshResponse:
    """Return a deterministic frontier-style mock when API keys are absent.

    Args:
        model: Frontier model name.
        prompt: Prompt text.
        context: Pipeline context for job ID.

    Returns:
        MeshResponse suitable for route escalation.

    Cost/quality target:
        Keep Sprint 1 fully functional offline while mimicking higher quality and
        higher cost than mesh-local models.
    """
    await asyncio.sleep(random.uniform(0.05, 0.16))
    return MeshResponse(
        model=model,
        provider_id=f"mock-frontier-{model}",
        content=(
            f"[{model} mock] High-confidence answer for job {context.job_id}. "
            f"Prompt summary: {prompt[:180]}"
        ),
        confidence=random.uniform(0.82, 0.96),
        self_critique="Mock frontier response; likely complete and well grounded.",
        latency_ms=random.randint(180, 520),
        cost_usd=random.uniform(0.003, 0.012),
        provider_paid_usd=0.0,
        proof_of_compute=f"mock-frontier-signature-{context.job_id}-{model}",
        external=True,
    )
