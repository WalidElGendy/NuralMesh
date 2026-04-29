import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.schemas import ChatMessage, PipelineContext
from app.stages import classify


def make_context(prompt: str = "Write a Python function to parse JSON.") -> PipelineContext:
    return PipelineContext(
        subscriber_id="sub_demo_pro",
        messages=[ChatMessage(role="user", content=prompt)],
    )


@pytest.mark.asyncio
async def test_litellm_valid_json_parses_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLASSIFY_MODEL", "llama-3.1-8b")
    monkeypatch.setenv("LLAMA_BASE_URL", "http://localhost:8001")
    monkeypatch.setattr(
        classify,
        "acompletion",
        AsyncMock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"domain":"code","complexity":"medium","sensitive":false,"confidence":0.91}'
                        )
                    )
                ],
                usage=SimpleNamespace(total_tokens=211),
            )
        ),
    )

    result = await classify.classify_stage(make_context())

    assert result.domain == "code"
    assert result.complexity == "medium"
    assert result.sensitive is False
    assert result.tokens_used == 211


@pytest.mark.asyncio
async def test_litellm_malformed_json_falls_back(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("CLASSIFY_MODEL", "llama-3.1-8b")
    monkeypatch.setenv("LLAMA_BASE_URL", "http://localhost:8001")
    monkeypatch.setattr(
        classify,
        "acompletion",
        AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))],
                usage=SimpleNamespace(total_tokens=13),
            )
        ),
    )

    with caplog.at_level(logging.WARNING):
        result = await classify.classify_stage(make_context())

    assert result.domain == "chat"
    assert result.complexity == "simple"
    assert result.sensitive is False
    assert "classify_fallback" in caplog.text


@pytest.mark.asyncio
async def test_litellm_exception_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLASSIFY_MODEL", "llama-3.1-8b")
    monkeypatch.setenv("LLAMA_BASE_URL", "http://localhost:8001")
    monkeypatch.setattr(classify, "acompletion", AsyncMock(side_effect=RuntimeError("boom")))

    result = await classify.classify_stage(make_context())

    assert result.domain == "chat"
    assert result.complexity == "simple"


@pytest.mark.asyncio
async def test_classify_model_mock_bypasses_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    completion = AsyncMock()
    monkeypatch.setenv("CLASSIFY_MODEL", "mock")
    monkeypatch.setattr(classify, "acompletion", completion)

    result = await classify.classify_stage(make_context("Please write Python code."))

    assert result.domain == "code"
    assert result.tokens_used == 0
    completion.assert_not_called()
