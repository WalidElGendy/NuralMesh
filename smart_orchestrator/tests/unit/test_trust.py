"""Tests for app.lib.trust  blockchain trust layer (identity, signing, registry)."""
import pytest
import fakeredis.aioredis as fakeredis

from app.lib.trust import (
    generate_node_keypair,
    fingerprint_request,
    sign_attestation,
    verify_attestation,
    register_node,
    record_attestation,
    get_attestation,
    is_node_trusted,
    flag_node,
)


@pytest.fixture
def redis():
    return fakeredis.FakeRedis()


def test_generate_keypair_produces_valid_hex():
    """Generated keypair should be 64-char hex strings."""
    priv, pub = generate_node_keypair()
    assert len(priv) == 64
    assert len(pub) == 64
    # Must be valid hex
    bytes.fromhex(priv)
    bytes.fromhex(pub)


def test_sign_and_verify_attestation():
    """A signature created with the private key should verify with the public key."""
    priv, pub = generate_node_keypair()
    fp = fingerprint_request("abc123", "llama-3.1-8b", 1700000000.0)
    sig = sign_attestation(priv, fp)
    assert verify_attestation(pub, fp, sig) is True


def test_verify_fails_with_wrong_key():
    """Verifying with a different public key should fail."""
    priv, pub = generate_node_keypair()
    _, wrong_pub = generate_node_keypair()
    fp = fingerprint_request("abc123", "llama-3.1-8b", 1700000000.0)
    sig = sign_attestation(priv, fp)
    assert verify_attestation(wrong_pub, fp, sig) is False


def test_fingerprint_is_deterministic():
    """Same inputs should always produce the same fingerprint."""
    fp1 = fingerprint_request("abc123", "llama-3.1-8b", 1700000000.0)
    fp2 = fingerprint_request("abc123", "llama-3.1-8b", 1700000000.0)
    assert fp1 == fp2
    assert len(fp1) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_record_and_retrieve_attestation(redis):
    """A valid signed attestation should be stored and retrievable."""
    priv, pub = generate_node_keypair()
    node_id = "node-test-001"
    req_id = "req-abc-001"

    await register_node(redis, node_id, pub)
    fp = fingerprint_request("deadbeef", "deepseek-v3", 1700000000.0)
    sig = sign_attestation(priv, fp)

    accepted = await record_attestation(redis, node_id, req_id, fp, sig)
    assert accepted is True

    record = await get_attestation(redis, req_id)
    assert record is not None
    assert record["node_id"] == node_id
    assert record["fingerprint"] == fp


@pytest.mark.asyncio
async def test_flag_node_marks_untrusted(redis):
    """Flagging a node should make is_node_trusted return False."""
    _, pub = generate_node_keypair()
    node_id = "node-bad-001"
    await register_node(redis, node_id, pub)
    assert await is_node_trusted(redis, node_id) is True
    await flag_node(redis, node_id)
    assert await is_node_trusted(redis, node_id) is False
