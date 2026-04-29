from app.models.schemas import MeshResponse, PipelineContext, RouteAttempt
from app.stages.verify import verify_response


async def test_verify_stage_passes_grounded_answer():
    context = PipelineContext(subscriber_id="sub_demo", system=None, messages=[])
    context.selected_response = MeshResponse(
        model="llama-3.1-8b",
        provider_id="provider-x",
        content="This is a grounded response.",
        confidence=0.9,
        self_critique="Looks grounded.",
        latency_ms=90,
        proof_of_compute="proof",
    )
    context.route_attempts.append(RouteAttempt(model="llama-3.1-8b", provider_id="provider-x", confidence=0.9, verifier_passed=False))
    await verify_response(context)
    assert context.verifier_verdict is not None
    assert context.route_attempts[-1].verifier_passed is True
