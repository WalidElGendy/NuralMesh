from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from app.config import AUTH_ENABLED
from app.lib.telemetry import tracer
from app.models.schemas import ApiKeyRecord
from app.stages.cache import get_redis_client


def hash_key(raw_key: str) -> str:
    """Hash a raw API key for Redis storage.

    Args:
        raw_key: Raw API key presented by the caller.

    Returns:
        SHA-256 hex digest of the key.

    Cost/quality target:
        Uses stdlib hashing only; raw keys are never stored or logged.
    """

    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def short_hash(raw_key_or_hash: str) -> str:
    """Return a safe short hash for observability.

    Args:
        raw_key_or_hash: Raw key or already-hashed key.

    Returns:
        First 16 hex characters safe for logs.

    Cost/quality target:
        Enables debugging without exposing raw credentials.
    """

    value = raw_key_or_hash if len(raw_key_or_hash) == 64 else hash_key(raw_key_or_hash)
    return value[:16]


def generate_key() -> str:
    """Generate a new NeuralMesh API key.

    Args:
        None.

    Returns:
        Raw key with recognizable nm_ prefix; caller returns it once.

    Cost/quality target:
        High-entropy stdlib-only key generation.
    """

    return "nm_" + secrets.token_urlsafe(32)


def _auth_enabled() -> bool:
    return os.getenv("AUTH_ENABLED", str(AUTH_ENABLED).lower()).lower() == "true"


def _record_from_hash(key_hash: str, data: dict[str, str]) -> ApiKeyRecord:
    return ApiKeyRecord(
        hash=key_hash,
        name=data.get("name", ""),
        tier=data.get("tier", "free"),
        created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        active=data.get("active", "0") == "1",
    )


async def ApiKeyDep(request: Request) -> ApiKeyRecord:
    """Validate Bearer API key and return the Redis key record.

    Args:
        request: FastAPI request containing Authorization: Bearer <key>.

    Returns:
        ApiKeyRecord for authenticated callers.

    Cost/quality target:
        One Redis hash lookup per protected request; bypassable with AUTH_ENABLED=false for CI/dev.
    """

    if not _auth_enabled():
        return ApiKeyRecord(
            hash="dev",
            name="dev",
            tier="admin",
            created_at=datetime.now(timezone.utc).isoformat(),
            active=True,
        )

    authorization = request.headers.get("authorization")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    raw_key = authorization.removeprefix("Bearer ").strip()
    key_hash = hash_key(raw_key)
    redis_client = get_redis_client()
    try:
        data = await redis_client.hgetall(f"auth:keys:{key_hash}")
    finally:
        close = getattr(redis_client, "aclose", None)
        if close is not None:
            await close()

    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    record = _record_from_hash(key_hash, data)
    if not record.active:
        raise HTTPException(status_code=401, detail="API key has been revoked")

    span = tracer.get_current_span() if hasattr(tracer, "get_current_span") else None
    if span is not None:
        span.set_attribute("auth.key_name", record.name)
    else:
        from opentelemetry import trace

        trace.get_current_span().set_attribute("auth.key_name", record.name)
    return record
