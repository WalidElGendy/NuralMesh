"""
Background worker that processes jobs from the Redis Streams queue.
Start with: python3 -m app.worker
"""
import asyncio
import logging
import os

import litellm

from app.lib.queue import STREAM_KEY, store_result
from app.lib.billing import record_usage
from app.stages.cache import get_redis_client

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "orchestrator-workers"
CONSUMER_NAME = "worker-1"
DEFAULT_MODEL = os.getenv("LLAMA_MODEL", "ollama/llama3.1:8b")


async def process_job(redis_client, job_id: str, fields: dict):
    """Run LLM for one job and store the result."""
    try:
        prompt = fields.get("prompt", "")
        model = fields.get("model_hint") or DEFAULT_MODEL
        key_hash = fields.get("key_hash", "")

        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        )
        content = response.choices[0].message.content
        tokens = response.usage.total_tokens if response.usage else 0

        await store_result(redis_client, job_id, {
            "status": "done",
            "result": content,
            "model": model,
            "tokens": str(tokens),
        })

        if key_hash:
            await record_usage(redis_client, key_hash, tokens)

    except Exception as exc:
        logger.error("Job %s failed: %s", job_id, exc)
        await store_result(redis_client, job_id, {
            "status": "error",
            "error": str(exc),
        })


async def main():
    redis_client = await get_redis_client()

    try:
        await redis_client.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception:
        pass

    logger.info("Worker started, listening on stream %s", STREAM_KEY)

    while True:
        try:
            messages = await redis_client.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {STREAM_KEY: ">"},
                count=1,
                block=1000,
            )
            if not messages:
                continue

            for stream_name, entries in messages:
                for entry_id, fields in entries:
                    if isinstance(entry_id, bytes):
                        entry_id = entry_id.decode()
                    decoded_fields = {}
                    for k, v in fields.items():
                        if isinstance(k, bytes):
                            k = k.decode()
                        if isinstance(v, bytes):
                            v = v.decode()
                        decoded_fields[k] = v

                    await process_job(redis_client, entry_id, decoded_fields)
                    await redis_client.xack(STREAM_KEY, CONSUMER_GROUP, entry_id)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Worker error: %s", exc)
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
