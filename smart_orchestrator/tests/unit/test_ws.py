import json
import pytest
import fakeredis.aioredis as fakeredis
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app


def make_fake_redis():
    return fakeredis.FakeRedis()


def _make_key_record():
    return type("K", (), {"hash": "abc", "tier": "free"})()


def _chunk(text):
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].delta.content = text
    return m


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


@patch("app.routers.ws.get_redis_client", new_callable=AsyncMock)
@patch("app.routers.ws.verify_api_key", new_callable=AsyncMock)
@patch("app.routers.ws.check_rate_limit", new_callable=AsyncMock)
@patch("app.routers.ws.record_usage", new_callable=AsyncMock)
@patch("app.routers.ws.litellm.completion")
def test_ws_streams_chunks(mock_litellm, mock_record, mock_rl, mock_verify, mock_redis):
    mock_redis.return_value = make_fake_redis()
    mock_verify.return_value = _make_key_record()
    mock_rl.return_value = None
    mock_litellm.return_value = [_chunk("Hi"), _chunk(" there")]

    client = TestClient(app)
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_text(json.dumps({"api_key": "valid", "prompt": "hello"}))
        msg1 = json.loads(ws.receive_text())
        assert msg1["type"] == "chunk"
        assert msg1["text"] == "Hi"


@patch("app.routers.ws.get_redis_client", new_callable=AsyncMock)
@patch("app.routers.ws.verify_api_key", new_callable=AsyncMock)
@patch("app.routers.ws.check_rate_limit", new_callable=AsyncMock)
@patch("app.routers.ws.record_usage", new_callable=AsyncMock)
@patch("app.routers.ws.litellm.completion")
def test_ws_sends_done_message(mock_litellm, mock_record, mock_rl, mock_verify, mock_redis):
    mock_redis.return_value = make_fake_redis()
    mock_verify.return_value = _make_key_record()
    mock_rl.return_value = None
    mock_litellm.return_value = [_chunk("Hi")]

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


@patch("app.routers.ws.get_redis_client", new_callable=AsyncMock)
@patch("app.routers.ws.verify_api_key", new_callable=AsyncMock)
@patch("app.routers.ws.check_rate_limit", new_callable=AsyncMock)
@patch("app.routers.ws.litellm.completion")
def test_ws_handles_litellm_error(mock_litellm, mock_rl, mock_verify, mock_redis):
    mock_redis.return_value = make_fake_redis()
    mock_verify.return_value = _make_key_record()
    mock_rl.return_value = None
    mock_litellm.side_effect = Exception("LLM unavailable")

    client = TestClient(app)
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_text(json.dumps({"api_key": "valid", "prompt": "hello"}))
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "error"
        assert "LLM unavailable" in msg["message"]
