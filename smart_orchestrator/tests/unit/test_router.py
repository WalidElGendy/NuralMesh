import pytest
from app.lib.router import get_ladder, resolve_model, pick_model, MODEL_MAP


def test_get_ladder_known():
    assert get_ladder("code") == ["qwen-coder-7b", "deepseek-v3", "claude-sonnet"]


def test_get_ladder_unknown():
    assert get_ladder("xyz") == get_ladder("chat")


def test_resolve_model():
    result = resolve_model("llama-3.1-8b")
    assert result == MODEL_MAP["llama-3.1-8b"]


def test_pick_model_free():
    model, remaining = pick_model("code", "free")
    assert model == resolve_model("qwen-coder-7b")
    assert remaining == ["deepseek-v3", "claude-sonnet"]


def test_pick_model_ultra():
    model, remaining = pick_model("code", "ultra")
    assert model == resolve_model("claude-sonnet")
    assert remaining == []
