import json
import os
import litellm
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.lib.auth import verify_api_key
from app.lib.ratelimit import check_and_increment as check_rate_limit
from app.lib.billing import record_usage
from app.stages.cache import get_redis_client

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
        model = data.get("model_hint") or DEFAULT_MODEL

        # Auth
        try:
            key_info = await verify_api_key(api_key, redis_client)
            key_hash = key_info.hash
            tier = key_info.tier
        except Exception:
            await websocket.close(code=4001)
            return

        # Rate limit
        try:
            await check_rate_limit(key_hash, tier, redis_client)
        except Exception:
            await websocket.close(code=4029)
            return

        # Stream LLM response
        try:
            total_tokens = 0
            response_stream = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            for chunk in response_stream:
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
