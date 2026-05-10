"""Tests for app.routers.provider and app.routers.admin_payouts."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _make_fake_redis():
    import fakeredis.aioredis as fakeredis
    return fakeredis.FakeRedis()


@pytest.fixture(autouse=True)
def patch_deps(monkeypatch):
    r = _make_fake_redis()
    monkeypatch.setattr("app.routers.provider.get_redis_client", AsyncMock(return_value=r))
    monkeypatch.setattr("app.routers.admin_payouts.get_redis_client", AsyncMock(return_value=r))
    # Make verify_api_key pass by default
    monkeypatch.setattr("app.routers.provider.verify_api_key", AsyncMock(return_value=MagicMock(tier="free")))
    return r


def test_provider_earnings_no_key_returns_401():
    """GET /provider/earnings/{node_id} without key should return 401."""
    resp = client.get("/provider/earnings/node-001")
    assert resp.status_code == 401


def test_provider_earnings_with_key_returns_dict():
    """GET /provider/earnings/{node_id} with valid key should return earnings dict."""
    resp = client.get("/provider/earnings/node-001", headers={"X-Api-Key": "test-key"})
    assert resp.status_code == 200
    data = resp.json()
    assert "total_usd" in data
    assert "pending_usd" in data
    assert data["node_id"] == "node-001"


def test_payout_no_key_returns_401():
    """POST /provider/payout without key should return 401."""
    resp = client.post("/provider/payout", json={
        "node_id": "node-001",
        "bank_account_name": "Test",
        "bank_iban_or_account": "US123",
        "bank_routing_or_swift": "021000021",
    })
    assert resp.status_code == 401


def test_admin_pending_payouts_wrong_secret_returns_403():
    """GET /admin/payouts/pending with wrong secret should return 403."""
    resp = client.get("/admin/payouts/pending", headers={"X-Admin-Secret": "wrong"})
    assert resp.status_code == 403


def test_admin_pending_payouts_correct_secret_returns_list():
    """GET /admin/payouts/pending with correct secret should return a list."""
    resp = client.get(
        "/admin/payouts/pending",
        headers={"X-Admin-Secret": "dev-admin-secret"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
