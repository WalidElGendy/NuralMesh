import pytest

from app.models.schemas import ChatMessage, PipelineContext, PromptClassification
from app.stages.route import route_stage


@pytest.mark.asyncio
async def test_route_stage_returns_answer():
    context = PipelineContext(
        subscriber_id="sub_demo_pro",
        messages=[ChatMessage(role="user", content="Write a Python function")],
        classification=PromptClassification(
            domain="code",
            complexity="simple",
            needs_freshness=False,
            sensitivity="none",
            expected_output_tokens=200,
        ),
    )
    await route_stage(context)
    assert context.answer is not None
    assert context.providers_touched
