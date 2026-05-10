"""Tests for GET /usage/me endpoint (Sprint 10)."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app


def _make_key_record(tier="free"):
    return type("K", (), {"hash": "testhash123", "tier": tier})()


def make_fake_redis():
    import fakeredis.aioredis
    return fakeredis.aioredis.FakeRedis()


# ---------------------------------------------------------------------------
# test_usage_me_no_key_returns_401
# ---------------------------------------------------------------------------
def test_usage_me_no_key_returns_401():
    client = TestClient(app)
    resp = client.get("/usage/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# test_usage_me_invalid_key_returns_401
# ---------------------------------------------------------------------------
@patch("app.routers.usage.get_redis_client", new_callable=AsyncMock)
@patch("app.routers.usage.verify_api_key", new_callable=AsyncMock)
def test_usage_me_invalid_key_returns_401(mock_verify, mock_redis):
    mock_redis.return_value = make_fake_redis()
    mock_verify.side_effect = Exception("invalid key")

    client = TestClient(app)
    resp = client.get("/usage/me", headers={"X-Api-Key": "bad"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# test_usage_me_returns_structure
# ---------------------------------------------------------------------------
@patch("app.routers.usage.get_redis_client", new_callable=AsyncMock)
@patch("app.routers.usage.verify_api_key", new_callable=AsyncMock)
def test_usage_me_returns_structure(mock_verify, mock_redis):
    mock_redis.return_value = make_fake_redis()
    mock_verify.return_value = _make_key_record()

    client = TestClient(app)
    resp = client.get("/usage/me", headers={"X-Api-Key": "valid"})
    assert resp.status_code == 200
    body = resp.json()
    assert "today" in body
    assert "total" in body
    assert "history" in body
    assert "tier" in body


# ---------------------------------------------------------------------------
# test_usage_me_history_length_default
# ---------------------------------------------------------------------------
@patch("app.routers.usage.get_redis_client", new_callable=AsyncMock)
@patch("app.routers.usage.verify_api_key", new_callable=AsyncMock)
def test_usage_me_history_length_default(mock_verify, mock_redis):
    mock_redis.return_value = make_fake_redis()
    mock_verify.return_value = _make_key_record()

    client = TestClient(app)
    resp = client.get("/usage/me", headers={"X-Api-Key": "valid"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["history"]) == 7  # default days=7
