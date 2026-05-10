from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.lib import litellm_client


@pytest.mark.asyncio
async def test_call_model_known_key_uses_mapped_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUTE_MODEL_PREFIX", "live")
    mock_completion = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))],
            usage=SimpleNamespace(total_tokens=12),
        )
    )
    monkeypatch.setattr(litellm_client, "acompletion", mock_completion)

    response = await litellm_client.call_model(
        "llama-3.1-8b",
        [{"role": "user", "content": "hello"}],
    )

    assert response.content == "hello"
    assert response.tokens == 12
    assert mock_completion.await_args.kwargs["model"] == "ollama/llama3.1:8b"


@pytest.mark.asyncio
async def test_call_model_unknown_key_raises() -> None:
    with pytest.raises(ValueError):
        await litellm_client.call_model("unknown", [{"role": "user", "content": "hello"}])


@pytest.mark.asyncio
async def test_route_model_prefix_mock_bypasses_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUTE_MODEL_PREFIX", "mock")
    mock_completion = AsyncMock()
    monkeypatch.setattr(litellm_client, "acompletion", mock_completion)

    response = await litellm_client.call_model(
        "llama-3.1-8b",
        [{"role": "user", "content": "hello"}],
    )

    assert response.content == "[MOCK]"
    assert response.tokens == 0
    mock_completion.assert_not_called()


@pytest.mark.asyncio
async def test_count_tokens_returns_positive_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm_client, "token_counter", MagicMock(return_value=17))

    count = await litellm_client.count_tokens(
        "llama-3.1-8b",
        [{"role": "user", "content": "hello"}],
    )

    assert count == 17
