from app.models.schemas import ChatMessage, PipelineContext
from app.stages.prune import prune_history


async def test_prune_history_keeps_short_history() -> None:
    """Ensure short histories pass through unchanged."""
    ctx = PipelineContext(
        subscriber_id="sub_demo",
        messages=[ChatMessage(role="user", content="hello")],
    )
    await prune_history(ctx)
    assert len(ctx.messages) == 1
