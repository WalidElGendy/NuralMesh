import pytest
from app.lib.router import choose_route, get_ladder, resolve_model, pick_model, MODEL_MAP


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


def test_auto_split_is_deterministic(monkeypatch):
    monkeypatch.setenv("NM_AUTO_ROUTE_GROQ_PERCENT", "20")
    first = choose_route(mode="auto", user_id="user-1", request_id="req-1", available_nodes=["node-a"])
    second = choose_route(mode="auto", user_id="user-1", request_id="req-1", available_nodes=["node-a"])
    assert first == second


def test_fast_mode_forces_groq():
    choice = choose_route(mode="fast", user_id="user-1", request_id="req-1", available_nodes=["node-a"])
    assert choice.route == "groq"
    assert choice.served_by == "groq"


def test_sovereign_mode_queues_without_nodes():
    choice = choose_route(mode="sovereign", user_id="user-1", request_id="req-1", available_nodes=[])
    assert choice.route == "sovereign"
    assert choice.queued is True
    assert choice.served_by is None
