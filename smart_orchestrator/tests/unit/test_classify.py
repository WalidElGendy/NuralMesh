import pytest

from app.models.schemas import ChatMessage, PipelineContext
from app.stages.classify import classify_stage


@pytest.mark.asyncio
async def test_classify_code_prompt() -> None:
    context = PipelineContext(
        subscriber_id="sub_demo_pro",
        messages=[ChatMessage(role="user", content="Write a Python function to parse JSON.")],
    )

    result = await classify_stage(context)

    assert result.domain == "code"
    assert context.classification == result
