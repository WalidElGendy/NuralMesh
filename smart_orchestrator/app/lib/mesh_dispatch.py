"""Mock Provider node-client dispatch for local mesh model execution."""

from __future__ import annotations

import asyncio
import random
import time
from hashlib import sha256
from uuid import uuid4

from app.lib.proof_of_compute import digest_text, sign_proof
from app.models.schemas import ChatMessage, ModelCallResult


LOCAL_MODELS = {
    "llama-3.1-8b",
    "mistral-7b",
    "qwen-coder-7b",
    "deepseek-v3-mesh",
    "deepseek-v3",
    "bge-large-en-v1.5",
}


def _prompt_text(messages: list[ChatMessage]) -> str:
    return "\n".join(f"{message.role}: {message.content}" for message in messages)


def _mock_answer(model: str, prompt: str) -> str:
    if model == "qwen-coder-7b":
        return "Here is a concise implementation plan with edge cases, tests, and a clean async interface."
    if model in {"deepseek-v3", "deepseek-v3-mesh"}:
        return "A deeper reasoning pass suggests decomposing the problem, validating assumptions, and returning a verified result."
    if model == "mistral-7b":
        return "Summary: earlier context was compressed into stable memory while preserving the latest user intent."
    if model == "bge-large-en-v1.5":
        return "Generated a 1024-dimensional semantic embedding."
    digest = sha256(prompt.encode("utf-8")).hexdigest()[:10]
    return f"NeuralMesh mock response from {model}. Answer fingerprint: {digest}. The request was processed successfully."


async def dispatch_to_provider(
    model: str, prompt: str, system: str | None = None, purpose: str = "inference"
) -> ModelCallResult:
    """Simulate dispatching work to a Provider node.

    Args:
        model: Local/provider-hosted model name.
        prompt: Prompt text sent to the model.
        system: Optional system prompt.
        purpose: Stage purpose for observability.

    Returns:
        ModelCallResult with mock text, confidence, latency, provider ID, and proof signature.

    Cost/quality target:
        Zero real cost, realistic latency, and deterministic-enough mock behavior for tests.
    """
    start = time.perf_counter()
    latency_ms = random.randint(50, 300)
    await asyncio.sleep(latency_ms / 1000)
    messages = [ChatMessage(role="user", content=prompt)]
    if system:
        messages.insert(0, ChatMessage(role="system", content=system))
    prompt_text = _prompt_text(messages)
    output = _mock_answer(model, prompt_text)
    confidence = round(random.uniform(0.66, 0.94), 3)
    if "hard" in prompt.lower() or "prove" in prompt.lower():
        confidence = min(confidence, 0.78)
    provider_id = f"provider-{random.randint(1000, 9999)}"
    proof = await sign_proof(
        provider_id=provider_id,
        model=model,
        prompt_digest=await digest_text(prompt_text),
        output_digest=await digest_text(output),
    )

    return ModelCallResult(
        model=model,
        provider_id=provider_id,
        content=output,
        confidence=confidence,
        self_critique="Mock provider reports no critical issues; verify stage should confirm grounding.",
        latency_ms=max(latency_ms, int((time.perf_counter() - start) * 1000)),
        proof_of_compute=proof,
        cost_usd=round(latency_ms / 1000 * 0.0004, 6),
        provider_paid_usd=round(latency_ms / 1000 * 0.00025, 6),
    )


async def dispatch_to_mesh(
    model: str, prompt: str, context: object | None = None, **kwargs: object
) -> ModelCallResult:
    """Compatibility wrapper for mocked mesh dispatch.

    Args:
        model: Local mesh model name.
        prompt: Prompt text.
        context: Optional pipeline context, unused by the mock.
        **kwargs: Extra routing metadata.

    Returns:
        Normalized mocked model result.

    Cost/quality target:
        Keeps all local model calls zero-key and swappable with future gRPC.
    """
    return await dispatch_to_provider(model=model, prompt=prompt, purpose=str(kwargs.get("task_type", "inference")))
