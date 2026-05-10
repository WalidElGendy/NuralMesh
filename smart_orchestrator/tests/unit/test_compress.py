import pytest

from app.models.schemas import ChatMessage, PipelineContext, PromptClassification
from app.stages.compress import compress_context


@pytest.mark.asyncio
async def test_compress_skips_short_prompt():
    ctx = PipelineContext(
        subscriber_id="sub_demo_pro",
        system=None,
        messages=[ChatMessage(role="user", content="short prompt")],
        classification=PromptClassification(
            domain="chat",
            complexity="simple",
            needs_freshness=False,
            sensitivity="none",
            expected_output_tokens=100,
        ),
    )
    await compress_context(ctx)
    assert ctx.compression_ratio == 1.0
