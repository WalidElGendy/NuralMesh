import asyncio
import json

STREAM_KEY = "orchestrator:jobs"
RESULT_PREFIX = "orchestrator:result:"


async def enqueue_job(redis_client, job: dict) -> str:
    """Add job to Redis Stream. Returns the stream entry ID (job_id)."""
    fields = {k: json.dumps(v) if not isinstance(v, str) else v for k, v in job.items()}
    job_id = await redis_client.xadd(STREAM_KEY, fields)
    if isinstance(job_id, bytes):
        job_id = job_id.decode()
    return str(job.get("job_id") or job_id)


async def store_result(redis_client, job_id: str, result: dict, ttl: int = 300):
    """Store job result in Redis hash with TTL."""
    key = RESULT_PREFIX + job_id
    string_result = {k: json.dumps(v) if not isinstance(v, str) else v for k, v in result.items()}
    await redis_client.hset(key, mapping=string_result)
    await redis_client.expire(key, ttl)


async def get_result(redis_client, job_id: str, timeout: int = 30) -> dict | None:
    """Poll for job result. Returns dict if found, None on timeout."""
    key = RESULT_PREFIX + job_id
    elapsed = 0.0
    while elapsed < timeout:
        data = await redis_client.hgetall(key)
        if data:
            decoded = {}
            for k, v in data.items():
                if isinstance(k, bytes):
                    k = k.decode()
                if isinstance(v, bytes):
                    v = v.decode()
                try:
                    decoded[k] = json.loads(v)
                except Exception:
                    decoded[k] = v
            return decoded
        await asyncio.sleep(0.5)
        elapsed += 0.5
    return None
