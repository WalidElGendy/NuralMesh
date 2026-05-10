"""Tests for app.routers.node  node trust REST API."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.lib.trust import generate_node_keypair, fingerprint_request, sign_attestation

client = TestClient(app)


def _fake_redis():
    import fakeredis.aioredis as fakeredis
    return fakeredis.FakeRedis()


@pytest.fixture(autouse=True)
def patch_redis(monkeypatch):
    """Patch get_redis_client to return an in-memory fakeredis instance."""
    r = _fake_redis()
    monkeypatch.setattr("app.routers.node.get_redis_client", AsyncMock(return_value=r))
    monkeypatch.setattr("app.lib.trust.logger", MagicMock())
    return r


def test_register_node_returns_registered():
    """POST /node/register should return status=registered for a valid public key."""
    _, pub = generate_node_keypair()
    resp = client.post("/node/register", json={"node_id": "node-001", "public_key_hex": pub})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "registered"
    assert data["node_id"] == "node-001"


def test_register_node_rejects_short_key():
    """POST /node/register should reject a public key that is not 64 hex chars."""
    resp = client.post("/node/register", json={"node_id": "node-002", "public_key_hex": "deadbeef"})
    assert resp.status_code == 400


def test_attest_unknown_node_not_accepted(patch_redis):
    """POST /node/attest for an unregistered node should return accepted=False."""
    _, pub = generate_node_keypair()
    priv, _ = generate_node_keypair()
    fp = fingerprint_request("hash123", "llama-3.1-8b", 1700000000.0)
    sig = sign_attestation(priv, fp)
    resp = client.post("/node/attest", json={
        "node_id": "unknown-node",
        "req_id": "req-001",
        "fingerprint": fp,
        "signature_hex": sig,
    })
    assert resp.status_code == 200
    assert resp.json()["accepted"] is False


def test_node_status_unregistered_not_trusted():
    """GET /node/{node_id} for an unknown node should return registered=False, trusted=False."""
    resp = client.get("/node/ghost-node-999")
    assert resp.status_code == 200
    data = resp.json()
    assert data["registered"] is False
    assert data["trusted"] is False
