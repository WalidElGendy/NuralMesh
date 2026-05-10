"""Tests for /health endpoint (Sprint 9)."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# test_health_returns_200
# ---------------------------------------------------------------------------
@patch("app.routers.health.get_redis_client", new_callable=AsyncMock)
def test_health_returns_200(mock_redis, client):
    mock_r = AsyncMock()
    mock_r.ping = AsyncMock(return_value=True)
    mock_redis.return_value = mock_r

    resp = client.get("/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# test_health_ok_when_redis_healthy
# ---------------------------------------------------------------------------
@patch("app.routers.health.get_redis_client", new_callable=AsyncMock)
def test_health_ok_when_redis_healthy(mock_redis, client):
    mock_r = AsyncMock()
    mock_r.ping = AsyncMock(return_value=True)
    mock_redis.return_value = mock_r

    resp = client.get("/health")
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["redis"] == "ok"


# ---------------------------------------------------------------------------
# test_health_degraded_when_redis_fails
# ---------------------------------------------------------------------------
@patch("app.routers.health.get_redis_client", new_callable=AsyncMock)
def test_health_degraded_when_redis_fails(mock_redis, client):
    mock_redis.side_effect = Exception("Connection refused")

    resp = client.get("/health")
    body = resp.json()
    assert body["status"] == "degraded"
    assert "error" in body["checks"]["redis"]


# ---------------------------------------------------------------------------
# test_health_has_latency_field
# ---------------------------------------------------------------------------
@patch("app.routers.health.get_redis_client", new_callable=AsyncMock)
def test_health_has_latency_field(mock_redis, client):
    mock_r = AsyncMock()
    mock_r.ping = AsyncMock(return_value=True)
    mock_redis.return_value = mock_r

    resp = client.get("/health")
    body = resp.json()
    assert "latency_s" in body
    assert isinstance(body["latency_s"], float)


# ---------------------------------------------------------------------------
# test_health_has_checks_field
# ---------------------------------------------------------------------------
@patch("app.routers.health.get_redis_client", new_callable=AsyncMock)
def test_health_has_checks_field(mock_redis, client):
    mock_r = AsyncMock()
    mock_r.ping = AsyncMock(return_value=True)
    mock_redis.return_value = mock_r

    resp = client.get("/health")
    body = resp.json()
    assert "checks" in body
    assert isinstance(body["checks"], dict)
