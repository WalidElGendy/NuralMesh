import pytest
from unittest.mock import AsyncMock

from app.models.schemas import ChatMessage, PipelineContext
from app.stages import prune


def make_history(turns: int = 8, words: int = 400) -> list[ChatMessage]:
    return [
        ChatMessage(role="user" if index % 2 == 0 else "assistant", content="word " * words)
        for index in range(turns)
    ]


@pytest.mark.asyncio
async def test_short_history_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prune, "PRUNE_THRESHOLD", 2000)
    ctx = PipelineContext(
        subscriber_id="sub_demo",
        messages=[ChatMessage(role="user", content="hello")],
    )

    result = await prune.prune_stage(ctx)

    assert result.history == [{"role": "user", "content": "hello"}]
    assert result.was_pruned is False


@pytest.mark.asyncio
async def test_long_history_summarized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUNE_MODEL_PREFIX", "live")
    monkeypatch.setattr(prune, "PRUNE_THRESHOLD", 10)
    call_model = AsyncMock(return_value=type("Resp", (), {"content": "Key facts and decisions."})())
    monkeypatch.setattr(prune, "call_model", call_model)
    ctx = PipelineContext(subscriber_id="sub_demo", messages=make_history())

    result = await prune.prune_stage(ctx)

    call_model.assert_awaited_once()
    assert result.was_pruned is True
    assert result.history[0]["role"] == "system"
    assert "Summary of earlier conversation" in result.history[0]["content"]
    assert result.pruned_tokens < result.original_tokens


@pytest.mark.asyncio
async def test_mistral_failure_returns_original(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUNE_MODEL_PREFIX", "live")
    monkeypatch.setattr(prune, "PRUNE_THRESHOLD", 10)
    monkeypatch.setattr(prune, "call_model", AsyncMock(side_effect=RuntimeError("down")))
    ctx = PipelineContext(subscriber_id="sub_demo", messages=make_history())

    result = await prune.prune_stage(ctx)

    assert result.was_pruned is False
    assert result.history == [message.model_dump() for message in ctx.messages]


@pytest.mark.asyncio
async def test_mock_prefix_returns_mock_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUNE_MODEL_PREFIX", "mock")
    monkeypatch.setattr(prune, "PRUNE_THRESHOLD", 10)
    call_model = AsyncMock()
    monkeypatch.setattr(prune, "call_model", call_model)
    ctx = PipelineContext(subscriber_id="sub_demo", messages=make_history())

    result = await prune.prune_stage(ctx)

    call_model.assert_not_called()
    assert result.was_pruned is True
    assert "[MOCK SUMMARY:" in result.history[0]["content"]


@pytest.mark.asyncio
async def test_empty_history_no_crash() -> None:
    ctx = PipelineContext(subscriber_id="sub_demo", messages=[])

    result = await prune.prune_stage(ctx)

    assert result.history == []
    assert result.was_pruned is False
