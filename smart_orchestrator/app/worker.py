import asyncio
import os
from app.lib.queue import store_result
from app.lib.billing import record_usage
from app.lib.mesh_dispatch import dispatch_to_mesh
from app.stages.cache import get_redis_client
from app.stages.classify import classify_prompt_simple

STREAM_KEY = "orchestrator:jobs"
CONSUMER_GROUP = "orchestrator-workers"
CONSUMER_NAME = "worker-1"

DEFAULT_MODEL = os.getenv("NM_NODE_MODEL", "llama3.3:70b-instruct-q4_K_M")


async def process_job(redis_client, job_id: str, fields: dict):
    prompt = fields.get("prompt", "")
    model_hint = fields.get("model_hint") or None
    mode = fields.get("mode") or "auto"
    key_hash = fields.get("key_hash", "")
    try:
        await classify_prompt_simple(prompt)
        response = await dispatch_to_mesh(
            model_hint or DEFAULT_MODEL,
            prompt,
            user_id=key_hash,
            request_id=job_id,
            mode=mode,
        )
        result_text = response.content or ""
        tokens = response.prompt_tokens + response.completion_tokens
        if key_hash:
            await record_usage(redis_client, key_hash, tokens)
        await store_result(redis_client, job_id, {
            "status": "done",
            "result": result_text,
            "model": response.model,
            "tokens": str(tokens),
            "prompt_tokens": str(response.prompt_tokens),
            "completion_tokens": str(response.completion_tokens),
            "latency_ms": str(response.latency_ms),
            "served_by": response.served_by or fields.get("served_by", ""),
        })
    except Exception as exc:
        await store_result(redis_client, job_id, {
            "status": "error",
            "error": str(exc),
        })


async def main():
    redis_client = await get_redis_client()
    try:
        await redis_client.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception:
        pass  # Group already exists

    while True:
        messages = await redis_client.xreadgroup(
            CONSUMER_GROUP, CONSUMER_NAME,
            {STREAM_KEY: ">"}, count=1, block=1000
        )
        if not messages:
            continue
        for stream_name, entries in messages:
            for entry_id, fields in entries:
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                decoded = {k.decode() if isinstance(k, bytes) else k:
                           v.decode() if isinstance(v, bytes) else v
                           for k, v in fields.items()}
                job_id = decoded.get("job_id", entry_id)
                await process_job(redis_client, job_id, decoded)
                await redis_client.xack(STREAM_KEY, CONSUMER_GROUP, entry_id)


if __name__ == "__main__":
    asyncio.run(main())
