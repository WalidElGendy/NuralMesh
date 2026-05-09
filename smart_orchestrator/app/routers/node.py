"""
Node Trust API  register inference nodes and submit attestations.

POST /node/register   : Register a node's Ed25519 public key
POST /node/attest     : Submit a signed attestation for a completed request
GET  /node/{node_id}  : Query a node's trust status
GET  /node/attest/{req_id} : Retrieve a stored attestation
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.stages.cache import get_redis_client
from app.lib.analytics import track_event
from app.lib.trust import (
    register_node,
    record_attestation,
    get_attestation,
    is_node_trusted,
    get_node_pubkey,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/node", tags=["trust"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class NodeRegisterRequest(BaseModel):
    node_id: str
    public_key_hex: str   # 64-char hex (32-byte Ed25519 public key)


class NodeRegisterResponse(BaseModel):
    node_id: str
    status: str           # "registered"


class AttestRequest(BaseModel):
    node_id: str
    req_id: str           # unique request ID (UUID or sha256 prefix)
    fingerprint: str      # sha256 of prompt_hash:model:timestamp
    signature_hex: str    # Ed25519 signature over fingerprint


class AttestResponse(BaseModel):
    req_id: str
    accepted: bool
    reason: Optional[str] = None


class NodeStatusResponse(BaseModel):
    node_id: str
    registered: bool
    trusted: bool
    public_key_hex: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register", response_model=NodeRegisterResponse)
async def register(body: NodeRegisterRequest):
    """Register (or update) an inference node's Ed25519 public key."""
    if len(body.public_key_hex) != 64:
        raise HTTPException(status_code=400, detail="public_key_hex must be 64 hex chars (32 bytes)")
    try:
        bytes.fromhex(body.public_key_hex)
    except ValueError:
        raise HTTPException(status_code=400, detail="public_key_hex is not valid hex")

    redis = await get_redis_client()
    await register_node(redis, body.node_id, body.public_key_hex)
    await track_event("node-online", body.node_id, {"source": "node.register"})
    return NodeRegisterResponse(node_id=body.node_id, status="registered")


@router.post("/attest", response_model=AttestResponse)
async def attest(body: AttestRequest):
    """Submit a cryptographically signed attestation for a completed inference request."""
    redis = await get_redis_client()
    accepted = await record_attestation(
        redis,
        node_id=body.node_id,
        req_id=body.req_id,
        fingerprint=body.fingerprint,
        signature_hex=body.signature_hex,
    )
    if accepted:
        return AttestResponse(req_id=body.req_id, accepted=True)
    else:
        return AttestResponse(
            req_id=body.req_id,
            accepted=False,
            reason="Unknown node or invalid signature",
        )


@router.get("/{node_id}", response_model=NodeStatusResponse)
async def node_status(node_id: str):
    """Query the trust status of an inference node."""
    redis = await get_redis_client()
    pubkey = await get_node_pubkey(redis, node_id)
    trusted = await is_node_trusted(redis, node_id)
    return NodeStatusResponse(
        node_id=node_id,
        registered=pubkey is not None,
        trusted=trusted,
        public_key_hex=pubkey,
    )


@router.get("/attest/{req_id}")
async def get_attest(req_id: str):
    """Retrieve a stored attestation record by request ID."""
    redis = await get_redis_client()
    record = await get_attestation(redis, req_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Attestation not found")
    return record
