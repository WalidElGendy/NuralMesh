from typing import Optional
from inspect import isawaitable
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from app.models.schemas import JobRequest, JobResult
from app.lib.auth import verify_api_key
from app.lib.billing import record_usage
from app.lib.groq_client import groq_client
from app.lib.ratelimit import check_and_increment as check_rate_limit
from app.lib.queue import enqueue_job, get_result, store_result
from app.lib.router import choose_route
from app.routers.admin import active_node_ids
from app.stages.cache import get_redis_client

router = APIRouter()


async def _get_redis_client():
    redis_client = get_redis_client()
    if isawaitable(redis_client):
        return await redis_client
    return redis_client


async def _authenticate_and_limit(x_api_key: str | None, redis_client) -> tuple[str, str]:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    try:
        key_info = await verify_api_key(x_api_key, redis_client)
        key_hash = key_info.hash
        tier = key_info.tier
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid API key")

    try:
        await check_rate_limit(key_hash, tier, redis_client)
    except Exception:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    return key_hash, tier


async def _complete_groq_job(redis_client, job_id: str, body: JobRequest, key_hash: str) -> dict:
    completion = await groq_client.complete_chat(
        [{"role": "user", "content": body.prompt}],
        user_id=key_hash,
    )
    await record_usage(redis_client, key_hash, completion.total_tokens)
    result = {
        "status": "done",
        "result": completion.content,
        "model": completion.model,
        "tokens": str(completion.total_tokens),
        "prompt_tokens": str(completion.prompt_tokens),
        "completion_tokens": str(completion.completion_tokens),
        "latency_ms": str(completion.latency_ms),
        "served_by": "groq",
    }
    await store_result(redis_client, job_id, result)
    return result


async def _submit(body: JobRequest, x_api_key: str | None) -> dict:
    redis_client = await _get_redis_client()
    key_hash, tier = await _authenticate_and_limit(x_api_key, redis_client)
    job_id = f"job_{uuid4().hex[:16]}"
    route = choose_route(
        mode=body.mode,
        user_id=key_hash,
        request_id=job_id,
        available_nodes=active_node_ids(),
    )
    if route.route == "groq":
        await _complete_groq_job(redis_client, job_id, body, key_hash)
        return {"job_id": job_id, "status": "done", "served_by": "groq"}

    job = {
        "job_id": job_id,
        "prompt": body.prompt,
        "model_hint": body.model_hint or "",
        "mode": body.mode,
        "key_hash": key_hash,
        "tier": tier,
        "served_by": route.served_by or "",
        "node_id": route.node_id or "",
    }
    job_id = await enqueue_job(redis_client, job)
    status = "queued"
    return {"job_id": job_id, "status": status, "served_by": route.served_by}


@router.post("", response_model=dict)
async def post_job(
    body: JobRequest,
    x_api_key: Optional[str] = Header(None),
):
    return await _submit(body, x_api_key)


@router.post("/submit", response_model=dict)
async def submit_job(
    body: JobRequest,
    x_api_key: Optional[str] = Header(None),
):
    return await _submit(body, x_api_key)


@router.get("/{job_id}", response_model=JobResult)
async def get_job(
    job_id: str,
    x_api_key: Optional[str] = Header(None),
):
    redis_client = await _get_redis_client()
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
        served_by=result.get("served_by"),
        error=result.get("error"),
    )
