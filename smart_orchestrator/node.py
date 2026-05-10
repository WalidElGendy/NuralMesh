
#!/usr/bin/env python3
"""
node.py  NeuralMesh GPU Node Agent

Run on any machine with a GPU to register it as an inference node.
Registers itself in the nodes table via the backend API,
then sends a heartbeat every 30 seconds.

Env vars:
  NODE_API_URL   Backend URL, e.g. https://api.neuralmesh.ai
  NODE_ID        Unique node identifier (auto-generated UUID if not set)
  NODE_NAME      Human-readable name (defaults to NODE_ID)
  NODE_LOCATION  e.g. "us-east", "eu-west" (default: "unknown")
  ADMIN_API_KEY  API key with admin tier for backend auth
  NM_NODE_MODEL   Default served model tag
  NM_NODE_MODELS  CSV list of served model tags
"""
from __future__ import annotations
import asyncio
import os
import subprocess
import uuid
import httpx
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [NODE] %(message)s")
logger = logging.getLogger(__name__)

NODE_API_URL = os.getenv("NODE_API_URL", "http://localhost:8000")
NODE_ID = os.getenv("NODE_ID", str(uuid.uuid4()))
NODE_NAME = os.getenv("NODE_NAME", NODE_ID)
NODE_LOCATION = os.getenv("NODE_LOCATION", "unknown")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY") or os.getenv("ADMIN_SECRET", "")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "30"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
NM_NODE_MODEL = os.getenv("NM_NODE_MODEL", "llama3.3:70b-instruct-q4_K_M")
NM_NODE_MODELS = [
    model.strip()
    for model in os.getenv("NM_NODE_MODELS", NM_NODE_MODEL).split(",")
    if model.strip()
]


async def _check_ollama_models() -> bool:
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_URL, timeout=5.0) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
    except Exception as exc:
        logger.error("Ollama self-check failed: %s", exc)
        return False

    installed = {model.get("name", "") for model in response.json().get("models", [])}
    missing = [model for model in NM_NODE_MODELS if model not in installed]
    if missing:
        logger.error("Ollama model(s) not pulled: %s", ", ".join(missing))
        return False
    return True


def _check_gpu_memory() -> bool:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        logger.error("GPU memory self-check failed: %s", exc)
        return False

    free_values = [int(value.strip()) for value in result.stdout.splitlines() if value.strip()]
    if not free_values:
        logger.error("GPU memory self-check returned no GPU rows")
        return False
    max_free_mb = max(free_values)
    if max_free_mb < 22 * 1024:
        logger.warning("Free GPU VRAM is below 22GB: %.2fGB", max_free_mb / 1024)
    return True


async def startup_self_check() -> None:
    if not await _check_ollama_models() or not _check_gpu_memory():
        logger.error("Node startup self-check failed; exiting")
        raise SystemExit(1)

async def register_and_heartbeat() -> None:
    headers = {"X-Admin-Secret": ADMIN_API_KEY} if ADMIN_API_KEY else {}
    payload = {
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "location": NODE_LOCATION,
        "model_versions": NM_NODE_MODELS,
    }
    logger.info("Starting node agent: id=%s name=%s location=%s", NODE_ID, NODE_NAME, NODE_LOCATION)
    async with httpx.AsyncClient(base_url=NODE_API_URL, headers=headers, timeout=10.0) as client:
        while True:
            try:
                resp = await client.post("/admin/nodes/heartbeat", json=payload)
                if resp.status_code in (200, 201):
                    logger.info("Heartbeat OK last_seen=%s", datetime.now(timezone.utc).isoformat())
                else:
                    logger.warning("Heartbeat failed status=%s body=%s", resp.status_code, resp.text[:100])
            except Exception as exc:
                logger.warning("Heartbeat exception: %s", exc)
            await asyncio.sleep(HEARTBEAT_INTERVAL)

if __name__ == "__main__":
    asyncio.run(startup_self_check())
    asyncio.run(register_and_heartbeat())
