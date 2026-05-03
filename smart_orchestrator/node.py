
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
"""
from __future__ import annotations
import asyncio
import os
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
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "30"))

async def register_and_heartbeat() -> None:
    headers = {"X-API-Key": ADMIN_API_KEY} if ADMIN_API_KEY else {}
    payload = {
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "location": NODE_LOCATION,
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
    asyncio.run(register_and_heartbeat())
