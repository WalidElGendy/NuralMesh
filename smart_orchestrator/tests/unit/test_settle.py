import pytest

from app.models.schemas import ChatMessage, PipelineContext
from app.stages import classify, route, settle, verify


@pytest.mark.asyncio
async def test_settle_writes_job_and_costs() -> None:
    context = PipelineContext(
        job_id="test-settle",
        subscriber_id="sub_demo_pro",
        messages=[ChatMessage(role="user", content="Explain neural routing.")],
    )
    await classify.run(context)
    await route.run(context)
    await verify.run(context)
    await settle.run(context)
    assert context.cost_usd > 0
    assert context.providers_paid > 0
