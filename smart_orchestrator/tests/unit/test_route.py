import pytest

from app.models.schemas import ChatMessage, ModelResponse, PipelineContext, PromptClassification
from app.stages import route


@pytest.fixture(autouse=True)
def legacy_route(monkeypatch):
    monkeypatch.setenv("NM_BETA_ROUTER_ENABLED", "false")


def make_context(domain: str = "code", sensitive: bool = False) -> PipelineContext:
    ctx = PipelineContext(
        subscriber_id="sub_demo_pro",
        messages=[ChatMessage(role="user", content="Write a Python function")],
        classification=PromptClassification(domain=domain, complexity="simple", sensitive=sensitive),
    )
    return ctx


def response(model: str, confidence: float, content: str | None = None) -> ModelResponse:
    return ModelResponse(content=content or f"answer\nConfidence: {confidence:.2f}", tokens=123)


@pytest.mark.asyncio
async def test_code_domain_uses_qwen_first(monkeypatch):
    monkeypatch.setenv("ROUTE_MODEL_PREFIX", "live")
    calls = []

    async def fake_call(model_key, messages, timeout=30):
        calls.append(model_key)
        return response(model_key, 0.9)

    monkeypatch.setattr(route, "call_model", fake_call)
    result = await route.route_stage(make_context())
    assert result.model_used == "qwen-coder-7b"
    assert result.escalation_count == 0
    assert calls == ["qwen-coder-7b"]


@pytest.mark.asyncio
async def test_code_domain_escalates_on_low_confidence(monkeypatch):
    monkeypatch.setenv("ROUTE_MODEL_PREFIX", "live")
    calls = []

    async def fake_call(model_key, messages, timeout=30):
        calls.append(model_key)
        return response(model_key, 0.5 if model_key == "qwen-coder-7b" else 0.88)

    monkeypatch.setattr(route, "call_model", fake_call)
    result = await route.route_stage(make_context())
    assert result.model_used == "deepseek-v3"
    assert result.escalation_count == 1
    assert calls == ["qwen-coder-7b", "deepseek-v3"]


@pytest.mark.asyncio
async def test_all_models_fail_returns_mock(monkeypatch):
    monkeypatch.setenv("ROUTE_MODEL_PREFIX", "live")
    async def failing_call(model_key, messages, timeout=30):
        raise RuntimeError("down")

    monkeypatch.setattr(route, "call_model", failing_call)
    result = await route.route_stage(make_context())
    assert result.response.startswith("[MOCK]")
    assert result.model_used == "mock-fallback"


@pytest.mark.asyncio
async def test_sensitive_jumps_to_claude(monkeypatch):
    monkeypatch.setenv("ROUTE_MODEL_PREFIX", "live")
    calls = []

    async def fake_call(model_key, messages, timeout=30):
        calls.append(model_key)
        return response(model_key, 0.9)

    monkeypatch.setattr(route, "call_model", fake_call)
    result = await route.route_stage(make_context(domain="code", sensitive=True))
    assert result.model_used == "claude-sonnet"
    assert result.sensitive_override is True
    assert calls == ["claude-sonnet"]


@pytest.mark.asyncio
async def test_route_model_prefix_mock(monkeypatch):
    monkeypatch.setenv("ROUTE_MODEL_PREFIX", "mock")
    result = await route.route_stage(make_context(domain="math"))
    assert result.model_used == "llama-3.1-8b"
    assert result.response == "[MOCK] Sprint 3 mocked response for domain=math"


@pytest.mark.asyncio
async def test_chat_single_model_ladder(monkeypatch):
    monkeypatch.setenv("ROUTE_MODEL_PREFIX", "live")
    calls = []

    async def fake_call(model_key, messages, timeout=30):
        calls.append(model_key)
        return response(model_key, 0.4)

    monkeypatch.setattr(route, "call_model", fake_call)
    result = await route.route_stage(make_context(domain="chat"))
    assert result.model_used == "llama-3.1-8b"
    assert result.escalation_count == 0
    assert calls == ["llama-3.1-8b"]


@pytest.mark.asyncio
async def test_missing_confidence_defaults_to_075(monkeypatch):
    monkeypatch.setenv("ROUTE_MODEL_PREFIX", "live")
    async def fake_call(model_key, messages, timeout=30):
        return ModelResponse(content="plain answer", tokens=77)

    monkeypatch.setattr(route, "call_model", fake_call)
    result = await route.route_stage(make_context())
    assert result.confidence == 0.75
    assert result.response == "plain answer"
