from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException

from app.config import ADMIN_SECRET
from app.lib.billing import get_usage
from app.lib.auth import generate_key, hash_key
from app.lib.metrics import get_metrics
from app.models.schemas import UsageRecord, CreateKeyRequest, CreateKeyResponse, KeyListItem
from app.stages.cache import get_redis_client

router = APIRouter()


def _require_admin_secret(x_admin_secret: str | None) -> None:
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid admin secret")


@router.post("/keys", response_model=CreateKeyResponse)
async def create_key(
    request: CreateKeyRequest, x_admin_secret: str | None = Header(default=None)
) -> CreateKeyResponse:
    """Create and store a hashed API key, returning the raw key once."""
    _require_admin_secret(x_admin_secret)
    raw_key = generate_key()
    key_hash = hash_key(raw_key)
    created_at = datetime.now(timezone.utc).isoformat()
    redis_client = get_redis_client()
    await redis_client.hset(
        f"auth:keys:{key_hash}",
        mapping={
            "name": request.name,
            "tier": request.tier,
            "created_at": created_at,
            "active": "1",
        },
    )
    return CreateKeyResponse(
        key=raw_key,
        hash=key_hash,
        name=request.name,
        tier=request.tier,
        created_at=created_at,
    )


@router.get("/keys", response_model=list[KeyListItem])
async def list_keys(x_admin_secret: str | None = Header(default=None)) -> list[KeyListItem]:
    """List stored API key metadata without exposing raw keys."""
    _require_admin_secret(x_admin_secret)
    redis_client = get_redis_client()
    items: list[KeyListItem] = []
    async for key in redis_client.scan_iter(match="auth:keys:*"):
        key_hash = str(key).split("auth:keys:", 1)[-1]
        data = await redis_client.hgetall(key)
        items.append(
            KeyListItem(
                hash=key_hash,
                name=data.get("name", ""),
                tier=data.get("tier", "free"),
                created_at=data.get("created_at", ""),
                active=str(data.get("active", "0")) == "1",
            )
        )
    return items


@router.delete("/keys/{key_hash}")
async def revoke_key(
    key_hash: str, x_admin_secret: str | None = Header(default=None)
) -> dict[str, str]:
    """Revoke an API key by marking it inactive."""
    _require_admin_secret(x_admin_secret)
    redis_client = get_redis_client()
    await redis_client.hset(f"auth:keys:{key_hash}", mapping={"active": "0"})
    return {"status": "revoked", "hash": key_hash}


@router.get("/stats")
async def stats(x_admin_secret: str | None = Header(default=None)) -> dict[str, float | int]:
    """Return the current in-memory metrics snapshot."""
    _require_admin_secret(x_admin_secret)
    return await get_metrics()


@router.get("/usage/{key_hash}", response_model=UsageRecord)
async def get_key_usage(key_hash: str, x_admin_secret: str | None = Header(None)):
    """Get usage stats for a specific API key."""
    _require_admin_secret(x_admin_secret)
    redis = await get_redis_client()
    return await get_usage(redis, key_hash)


@router.get("/usage", response_model=list[UsageRecord])
async def list_usage(x_admin_secret: str | None = Header(None)):
    """List usage stats for all API keys."""
    _require_admin_secret(x_admin_secret)
    redis = await get_redis_client()
    keys = []
    async for key in redis.scan_iter("usage:*"):
        key_hash = key.decode().split(":", 1)[1] if isinstance(key, bytes) else key.split(":", 1)[1]
        usage = await get_usage(redis, key_hash)
        keys.append(usage)
    return keys
