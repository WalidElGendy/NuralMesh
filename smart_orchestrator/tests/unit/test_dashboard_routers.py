"""Tests for user_dashboard and gpu_dashboard routers."""
import pytest
import fakeredis
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_user_dashboard_html(client):
    resp = client.get("/user/dashboard")
    assert resp.status_code == 200
    assert "NeuralMesh" in resp.text
    assert "AI Usage Dashboard" in resp.text
    assert "text/html" in resp.headers["content-type"]


def test_gpu_dashboard_html(client):
    resp = client.get("/gpu/dashboard")
    assert resp.status_code == 200
    assert "NeuralMesh Provider" in resp.text
    assert "Request Payout" in resp.text
    assert "text/html" in resp.headers["content-type"]


def test_user_stats_no_key(client):
    resp = client.get("/user/stats")
    assert resp.status_code == 401
    assert "error" in resp.json()


def test_gpu_stats_endpoint(client):
    with patch("app.routers.gpu_dashboard.get_redis_client") as mock_redis:
        mock_redis.return_value = fakeredis.FakeRedis()
        resp = client.get("/gpu/stats/test-node-123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["node_id"] == "test-node-123"
    assert "total_earned_usd" in data


def test_gpu_network_endpoint(client):
    with patch("app.routers.gpu_dashboard.get_redis_client") as mock_redis:
        mock_redis.return_value = fakeredis.FakeRedis()
        resp = client.get("/gpu/network")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_nodes" in data
    assert "uptime_pct" in data
