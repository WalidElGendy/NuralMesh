import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.lib.router import resolve_model


def _make_response(content="hello", tokens=5):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage = MagicMock()
    resp.usage.total_tokens = tokens
    return resp


@pytest.mark.asyncio
@patch("app.lib.escalation.record_usage", new_callable=AsyncMock)
@patch("app.lib.escalation.litellm.completion")
async def test_escalation_success_first_try(mock_completion, mock_record):
    mock_completion.return_value = _make_response()
    from app.lib.escalation import call_with_escalation
    import fakeredis.aioredis as fakeredis
    r = await fakeredis.FakeRedis()
    response, model, tokens = await call_with_escalation(
        "hello", "chat", "free", r, "hash123", stream=False
    )
    assert model == resolve_model("llama-3.1-8b")
    assert mock_completion.call_count == 1


@pytest.mark.asyncio
@patch("app.lib.escalation.record_usage", new_callable=AsyncMock)
@patch("app.lib.escalation.litellm.completion")
async def test_escalation_escalates_on_failure(mock_completion, mock_record):
    # First call fails, second succeeds
    mock_completion.side_effect = [Exception("first fail"), _make_response()]
    from app.lib.escalation import call_with_escalation
    import fakeredis.aioredis as fakeredis
    r = await fakeredis.FakeRedis()
    response, model, tokens = await call_with_escalation(
        "write code", "code", "free", r, "hash123", stream=False
    )
    # code ladder free=qwen-coder-7b, escalates to deepseek-v3
    assert model == resolve_model("deepseek-v3")
    assert mock_completion.call_count == 2


@pytest.mark.asyncio
@patch("app.lib.escalation.record_usage", new_callable=AsyncMock)
@patch("app.lib.escalation.litellm.completion")
async def test_escalation_raises_when_all_fail(mock_completion, mock_record):
    mock_completion.side_effect = Exception("all fail")
    from app.lib.escalation import call_with_escalation
    import fakeredis.aioredis as fakeredis
    r = await fakeredis.FakeRedis()
    with pytest.raises(Exception, match="all fail"):
        await call_with_escalation(
            "hello", "chat", "free", r, "hash123", stream=False
        )
