from typing import Optional
from fastapi import APIRouter, Header, HTTPException
from app.models.schemas import JobRequest, JobResult
from app.lib.auth import verify_api_key
from app.lib.ratelimit import check_and_increment as check_rate_limit
from app.lib.queue import enqueue_job, get_result
from app.stages.cache import get_redis_client

router = APIRouter()


@router.post("", response_model=dict)
async def post_job(
    body: JobRequest,
    x_api_key: Optional[str] = Header(None),
):
    redis_client = await get_redis_client()
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    try:
        key_info = await verify_api_key(x_api_key, redis_client)
        key_hash = key_info["key_hash"]
        tier = key_info.get("tier", "free")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid API key")

    try:
        await check_rate_limit(key_hash, tier, redis_client)
    except Exception:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    job = {
        "prompt": body.prompt,
        "model_hint": body.model_hint or "",
        "key_hash": key_hash,
        "tier": tier,
    }
    job_id = await enqueue_job(redis_client, job)
    return {"job_id": job_id, "status": "queued"}


@router.get("/{job_id}", response_model=JobResult)
async def get_job(
    job_id: str,
    x_api_key: Optional[str] = Header(None),
):
    redis_client = await get_redis_client()
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    try:
        await verify_api_key(x_api_key, redis_client)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid API key")

    result = await get_result(redis_client, job_id, timeout=0)
    if result is None:
        return JobResult(job_id=job_id, status="pending")

    return JobResult(
        job_id=job_id,
        status=result.get("status", "done"),
        result=result.get("result"),
        model=result.get("model"),
        tokens=int(result["tokens"]) if result.get("tokens") else None,
        error=result.get("error"),
    )
