import json
import os
import litellm
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.lib.auth import verify_api_key
from app.lib.ratelimit import check_and_increment as check_rate_limit
from app.lib.billing import record_usage
from app.lib.escalation import call_with_escalation
from app.stages.cache import get_redis_client
from app.stages.classify import classify_prompt_simple

router = APIRouter()

DEFAULT_MODEL = os.getenv("LLAMA_MODEL", "ollama/llama3.1:8b")


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    redis_client = await get_redis_client()
    try:
        raw = await websocket.receive_text()
        try:
            data = json.loads(raw)
        except Exception:
            await websocket.send_text(json.dumps({"type": "error", "message": "invalid json"}))
            await websocket.close()
            return

        api_key = data.get("api_key", "")
        prompt = data.get("prompt", "")
        model_hint = data.get("model_hint") or None

        # Auth
        try:
            key_record = await verify_api_key(api_key, redis_client)
        except Exception:
            await websocket.close(code=4001)
            return

        key_hash = key_record.hash
        tier = key_record.tier

        # Rate limit
        try:
            await check_rate_limit(key_hash, tier, redis_client)
        except Exception:
            await websocket.close(code=4029)
            return

        # Classify & escalate
        try:
            category = await classify_prompt_simple(prompt)
            stream, model, _ = await call_with_escalation(
                prompt, category, tier, redis_client, key_hash,
                hint=model_hint, stream=True
            )
            total_tokens = 0
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta is None:
                    continue
                total_tokens += 1
                await websocket.send_text(json.dumps({"type": "chunk", "text": delta}))
            await record_usage(redis_client, key_hash, total_tokens)
            await websocket.send_text(json.dumps({"type": "done", "model": model, "tokens": total_tokens}))
            await websocket.close()
        except Exception as e:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
            await websocket.close()
    except WebSocketDisconnect:
        pass
