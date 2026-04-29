from __future__ import annotations

from app.lib.mesh_dispatch import dispatch_to_mesh
from app.models.schemas import PipelineContext, VerifierVerdict


async def verify_answer(context: PipelineContext, response: object, model: str | None = None) -> VerifierVerdict:
    """Verify a candidate answer with a mocked hallucination verifier.

    Args:
        context: Pipeline context with prompt and classification metadata.
        answer: Candidate answer text.
        model: Model that produced the answer.

    Returns:
        Verifier verdict used by routing to accept or escalate.

    Cost/quality target:
        Cheap local verifier, optimized to prevent low-confidence answers from
        stopping cascade escalation too early.
    """
    answer_text = getattr(response, "content", response if isinstance(response, str) else "")
    model_name = model or getattr(response, "model", "unknown")
    verifier_response = await dispatch_to_mesh(
        "llama-3.1-8b",
        f"Verify answer from {model_name}: {answer_text[:500]}",
        task_type="verify",
    )
    context.provider_touches.append(verifier_response)
    context.providers_touched.append(verifier_response)
    risk = max(0.02, 1.0 - verifier_response.confidence)
    pass_ = verifier_response.confidence >= 0.62 and "unsupported" not in answer_text.lower()
    return VerifierVerdict(
        grounded=pass_,
        hallucination_risk=round(risk, 3),
        factual_claims=[
            "answer follows requested task",
            f"domain classified as {context.classification.domain if context.classification else 'unknown'}",
        ],
        pass_=pass_,
    )


async def verify_response(context: PipelineContext) -> PipelineContext:
    """Verify the selected response and update the latest route attempt.

    Args:
        context: Pipeline context with selected_response set.

    Returns:
        Context with verifier_verdict attached.

    Cost/quality target:
        Reuses the mocked local verifier to keep Sprint 1 zero-key.
    """
    if context.selected_response is None:
        raise ValueError("selected_response is required")
    verdict = await verify_answer(context, context.selected_response)
    context.verifier_verdict = verdict
    if context.route_attempts:
        context.route_attempts[-1].verifier_passed = verdict.pass_
    return context


run = verify_response
