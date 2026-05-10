"""
Blockchain Trust Layer  cryptographic identity and attestation for inference nodes.

This is a TRUST layer, NOT a finance layer:
  - Each node has an Ed25519 keypair (its identity).
  - Nodes sign request fingerprints (sha256 of prompt hash + model + timestamp).
  - The orchestrator verifies signatures and maintains a Redis-backed trust registry.
  - No tokens, no payments  only cryptographic proof of honest computation.

Key concepts:
  - Node Identity  : Ed25519 keypair; public key is the node's address.
  - Attestation    : A signed record proving a node handled a specific request.
  - Trust Registry : Redis HASH mapping node_id -> {public_key, attested_count, flagged}.
"""
import hashlib
import json
import time
import logging
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption,
)
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)

# Redis key layout
TRUST_NODE_KEY = "trust:node:{node_id}"      # HASH: pubkey_hex, attested_count, flagged
TRUST_ATTEST_KEY = "trust:attest:{req_id}"   # STRING: JSON attestation record (TTL 7d)
TRUST_ATTEST_TTL = 7 * 24 * 3600             # 7 days


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

def generate_node_keypair() -> tuple[str, str]:
    """
    Generate a new Ed25519 keypair.
    Returns (private_key_hex, public_key_hex).
    Private key must be stored securely by the node operator.
    """
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private_bytes.hex(), public_bytes.hex()


def _load_private_key(private_hex: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex))


def _load_public_key(public_hex: str) -> Ed25519PublicKey:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as PK
    return PK.from_public_bytes(bytes.fromhex(public_hex))


# ---------------------------------------------------------------------------
# Request fingerprinting
# ---------------------------------------------------------------------------

def fingerprint_request(prompt_hash: str, model: str, timestamp: float) -> str:
    """
    Deterministic sha256 fingerprint of a request.
    prompt_hash  : sha256(prompt.encode()).hexdigest()[:16]  (never log the full prompt)
    model        : model name used
    timestamp    : unix timestamp of the call
    """
    payload = f"{prompt_hash}:{model}:{timestamp:.3f}"
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Attestation signing / verification
# ---------------------------------------------------------------------------

def sign_attestation(private_hex: str, fingerprint: str) -> str:
    """
    Sign a request fingerprint with the node's private key.
    Returns signature as hex string.
    """
    private_key = _load_private_key(private_hex)
    sig = private_key.sign(fingerprint.encode())
    return sig.hex()


def verify_attestation(public_hex: str, fingerprint: str, signature_hex: str) -> bool:
    """
    Verify a signature against a fingerprint using a node's public key.
    Returns True if valid, False otherwise.
    """
    try:
        public_key = _load_public_key(public_hex)
        public_key.verify(bytes.fromhex(signature_hex), fingerprint.encode())
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


# ---------------------------------------------------------------------------
# Trust registry (Redis-backed)
# ---------------------------------------------------------------------------

async def register_node(redis_client, node_id: str, public_hex: str) -> None:
    """
    Register a node's public key in the trust registry.
    Idempotent  re-registering updates the public key.
    """
    key = TRUST_NODE_KEY.format(node_id=node_id)
    await redis_client.hset(key, mapping={
        "pubkey_hex": public_hex,
        "attested_count": 0,
        "flagged": 0,
    })
    logger.info("Trust: registered node %s", node_id)


async def get_node_pubkey(redis_client, node_id: str) -> Optional[str]:
    """Return the registered public key hex for a node, or None."""
    key = TRUST_NODE_KEY.format(node_id=node_id)
    raw = await redis_client.hget(key, "pubkey_hex")
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else raw


async def record_attestation(
    redis_client,
    node_id: str,
    req_id: str,
    fingerprint: str,
    signature_hex: str,
) -> bool:
    """
    Verify and record an attestation from a node.
    Returns True if signature is valid and attestation is stored.
    Returns False if node is unknown or signature is invalid.
    """
    pubkey_hex = await get_node_pubkey(redis_client, node_id)
    if pubkey_hex is None:
        logger.warning("Trust: unknown node %s attempted attestation", node_id)
        return False

    if not verify_attestation(pubkey_hex, fingerprint, signature_hex):
        logger.warning("Trust: invalid signature from node %s for req %s", node_id, req_id)
        return False

    # Store attestation record
    attest_key = TRUST_ATTEST_KEY.format(req_id=req_id)
    record = json.dumps({
        "node_id": node_id,
        "req_id": req_id,
        "fingerprint": fingerprint,
        "signature": signature_hex,
        "ts": time.time(),
    })
    await redis_client.set(attest_key, record, ex=TRUST_ATTEST_TTL)

    # Increment attested_count for node
    node_key = TRUST_NODE_KEY.format(node_id=node_id)
    await redis_client.hincrby(node_key, "attested_count", 1)

    logger.info("Trust: attestation recorded for req %s by node %s", req_id, node_id)
    return True


async def get_attestation(redis_client, req_id: str) -> Optional[dict]:
    """Retrieve a stored attestation by request ID."""
    attest_key = TRUST_ATTEST_KEY.format(req_id=req_id)
    raw = await redis_client.get(attest_key)
    if raw is None:
        return None
    return json.loads(raw.decode() if isinstance(raw, bytes) else raw)


async def flag_node(redis_client, node_id: str) -> None:
    """Flag a node as untrusted (e.g., after repeated invalid attestations)."""
    key = TRUST_NODE_KEY.format(node_id=node_id)
    await redis_client.hset(key, "flagged", 1)
    logger.warning("Trust: node %s has been flagged as untrusted", node_id)


async def is_node_trusted(redis_client, node_id: str) -> bool:
    """Return True if node is registered and not flagged."""
    key = TRUST_NODE_KEY.format(node_id=node_id)
    flagged = await redis_client.hget(key, "flagged")
    if flagged is None:
        return False   # not registered
    val = int(flagged.decode() if isinstance(flagged, bytes) else flagged)
    return val == 0
