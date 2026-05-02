import asyncio
import json
import os
import litellm
from app.lib.queue import enqueue_job, store_result, get_result
from app.lib.billing import record_usage
from app.lib.escalation import call_with_escalation
from app.stages.cache import get_redis_client
from app.stages.classify import classify_prompt_simple

STREAM_KEY = "orchestrator:jobs"
CONSUMER_GROUP = "orchestrator-workers"
CONSUMER_NAME = "worker-1"

DEFAULT_MODEL = os.getenv("LLAMA_MODEL", "ollama/llama3.1:8b")


async def process_job(redis_client, job_id: str, fields: dict):
    prompt = fields.get("prompt", "")
    model_hint = fields.get("model_hint") or None
    try:
        category = await classify_prompt_simple(prompt)
        response, model_used, tokens = await call_with_escalation(
            prompt, category, "free", redis_client, job_id,
            hint=model_hint, stream=False
        )
        result_text = response.choices[0].message.content
        await store_result(redis_client, job_id, {
            "status": "done",
            "result": result_text,
            "model": model_used,
            "tokens": str(tokens),
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
