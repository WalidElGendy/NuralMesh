"""Tests for WebSocket /ws/chat endpoint (Sprint 7/8 compatible)."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app


def make_fake_redis():
    import fakeredis.aioredis
    return fakeredis.aioredis.FakeRedis()


def _make_key_record():
    return type("K", (), {"hash": "abc123", "tier": "free"})()


# ---------------------------------------------------------------------------
# test_ws_rejects_invalid_key
# ---------------------------------------------------------------------------
@patch("app.routers.ws.get_redis_client", new_callable=AsyncMock)
@patch("app.routers.ws.verify_api_key", new_callable=AsyncMock)
def test_ws_rejects_invalid_key(mock_verify, mock_redis):
    mock_redis.return_value = make_fake_redis()
    mock_verify.side_effect = Exception("invalid key")

    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_text(json.dumps({"api_key": "bad", "prompt": "hello"}))
            ws.receive_text()


# ---------------------------------------------------------------------------
# test_ws_rejects_rate_limited
# ---------------------------------------------------------------------------
@patch("app.routers.ws.get_redis_client", new_callable=AsyncMock)
@patch("app.routers.ws.verify_api_key", new_callable=AsyncMock)
@patch("app.routers.ws.check_rate_limit", new_callable=AsyncMock)
def test_ws_rejects_rate_limited(mock_rl, mock_verify, mock_redis):
    mock_redis.return_value = make_fake_redis()
    mock_verify.return_value = _make_key_record()
    mock_rl.side_effect = Exception("rate limited")

    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_text(json.dumps({"api_key": "valid", "prompt": "hello"}))
            ws.receive_text()


# ---------------------------------------------------------------------------
# test_ws_streams_chunks
# ---------------------------------------------------------------------------
@patch("app.routers.ws.get_redis_client", new_callable=AsyncMock)
@patch("app.routers.ws.verify_api_key", new_callable=AsyncMock)
@patch("app.routers.ws.check_rate_limit", new_callable=AsyncMock)
@patch("app.routers.ws.classify_prompt_simple", new_callable=AsyncMock)
@patch("app.routers.ws.call_with_escalation", new_callable=AsyncMock)
@patch("app.routers.ws.record_usage", new_callable=AsyncMock)
def test_ws_streams_chunks(mock_record, mock_escalate, mock_classify,
                           mock_rl, mock_verify, mock_redis):
    mock_redis.return_value = make_fake_redis()
    mock_verify.return_value = _make_key_record()
    mock_rl.return_value = None
    mock_classify.return_value = "chat"

    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = "Hi"
    mock_escalate.return_value = ([chunk], "llama-3.1-8b", 0)

    client = TestClient(app)
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_text(json.dumps({"api_key": "valid", "prompt": "hello"}))
        messages = []
        for _ in range(5):
            try:
                messages.append(json.loads(ws.receive_text()))
            except Exception:
                break

    chunk_msgs = [m for m in messages if m.get("type") == "chunk"]
    assert len(chunk_msgs) >= 1
    assert chunk_msgs[0]["text"] == "Hi"


# ---------------------------------------------------------------------------
# test_ws_sends_done_message
# ---------------------------------------------------------------------------
@patch("app.routers.ws.get_redis_client", new_callable=AsyncMock)
@patch("app.routers.ws.verify_api_key", new_callable=AsyncMock)
@patch("app.routers.ws.check_rate_limit", new_callable=AsyncMock)
@patch("app.routers.ws.classify_prompt_simple", new_callable=AsyncMock)
@patch("app.routers.ws.call_with_escalation", new_callable=AsyncMock)
@patch("app.routers.ws.record_usage", new_callable=AsyncMock)
def test_ws_sends_done_message(mock_record, mock_escalate, mock_classify,
                               mock_rl, mock_verify, mock_redis):
    mock_redis.return_value = make_fake_redis()
    mock_verify.return_value = _make_key_record()
    mock_rl.return_value = None
    mock_classify.return_value = "chat"

    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = "Hi"
    mock_escalate.return_value = ([chunk], "llama-3.1-8b", 0)

    client = TestClient(app)
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_text(json.dumps({"api_key": "valid", "prompt": "hello"}))
        messages = []
        for _ in range(5):
            try:
                messages.append(json.loads(ws.receive_text()))
            except Exception:
                break

    done_msgs = [m for m in messages if m.get("type") == "done"]
    assert len(done_msgs) == 1
    assert "model" in done_msgs[0]
    assert "tokens" in done_msgs[0]


# ---------------------------------------------------------------------------
# test_ws_handles_llm_error
# ---------------------------------------------------------------------------
@patch("app.routers.ws.get_redis_client", new_callable=AsyncMock)
@patch("app.routers.ws.verify_api_key", new_callable=AsyncMock)
@patch("app.routers.ws.check_rate_limit", new_callable=AsyncMock)
@patch("app.routers.ws.classify_prompt_simple", new_callable=AsyncMock)
@patch("app.routers.ws.call_with_escalation", new_callable=AsyncMock)
def test_ws_handles_llm_error(mock_escalate, mock_classify,
                              mock_rl, mock_verify, mock_redis):
    mock_redis.return_value = make_fake_redis()
    mock_verify.return_value = _make_key_record()
    mock_rl.return_value = None
    mock_classify.return_value = "chat"
    mock_escalate.side_effect = Exception("LLM unavailable")

    client = TestClient(app)
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_text(json.dumps({"api_key": "valid", "prompt": "hello"}))
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "error"
        assert "LLM unavailable" in msg["message"]
