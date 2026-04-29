import pytest

from app.models.schemas import ChatMessage, PipelineContext
from app.stages.cache import semantic_cache_stage


@pytest.mark.asyncio
async def test_cache_skips_sensitive_prompt() -> None:
    ctx = PipelineContext(subscriber_id="sub_demo_pro", messages=[ChatMessage(role="user", content="private")])
    ctx.classification = type("Classification", (), {"sensitivity": "pii", "needs_freshness": False, "domain": "chat"})()
    updated = await semantic_cache_stage(ctx)
    assert updated.cache_hit is None
