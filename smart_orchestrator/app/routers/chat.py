from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.lib.chat_auth import BetaChatUserDep, ChatUser
from app.lib.chat_history import ChatHistoryStore, generate_title, get_chat_history_store
from app.lib.ratelimit import RateLimiter
from app.models.schemas import ChatMessage, ChatRequest, ChatResponse, StageEvent
from app.pipeline import run_pipeline
from app.stages.cache import get_redis_client


router = APIRouter(prefix="/api", tags=["chat"])

Mode = Literal["auto", "sovereign", "fast"]
DEFAULT_MODEL = "llama-3.3-70b"


class ChatApiRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1)
    mode: Mode = "auto"
    model: str = DEFAULT_MODEL


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def get_store() -> ChatHistoryStore:
    return get_chat_history_store()


def _sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _served_by(mode: Mode, response: ChatResponse) -> str:
    if response.served_by == "groq":
        return "Groq"
    if response.served_by and response.served_by.startswith("node:"):
        return f"Sovereign — {response.served_by.removeprefix('node:')}"
    if mode == "fast":
        return "Groq"
    seed = response.route_model or response.job_id or "sovereign"
    node_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:4]
    return f"Sovereign — node-{node_id}"


async def enforce_chat_rate_limit(
    response: Response,
    user: ChatUser = Depends(BetaChatUserDep),
) -> ChatUser:
    redis_client = get_redis_client()
    result = await RateLimiter(redis_client, user.tier).check_and_increment(
        f"chat:{user.user_id}",
        user.tier,
    )
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    response.headers["X-RateLimit-Reset"] = str(result.reset_at)
    return user


async def _pipeline_messages(
    store: ChatHistoryStore,
    user: ChatUser,
    conversation_id: str,
    latest_message: str,
) -> list[ChatMessage]:
    persisted = await store.list_messages(user.user_id, conversation_id)
    messages = [
        ChatMessage(role=message["role"], content=message["content"])
        for message in persisted
        if message["role"] in {"user", "assistant", "system"}
    ]
    if not messages or messages[-1].content != latest_message:
        messages.append(ChatMessage(role="user", content=latest_message))
    return messages


async def _stream_chat_turn(
    *,
    store: ChatHistoryStore,
    user: ChatUser,
    api_request: ChatApiRequest,
    conversation: dict[str, object],
    user_message: dict[str, object],
) -> AsyncIterator[str]:
    started = time.perf_counter()
    stage_queue: asyncio.Queue[StageEvent | None] = asyncio.Queue()

    async def emit_stage(event: StageEvent) -> None:
        await stage_queue.put(event)

    async def execute_pipeline() -> ChatResponse:
        messages = await _pipeline_messages(
            store,
            user,
            str(conversation["id"]),
            api_request.message,
        )
        request = ChatRequest(
            subscriber_id="sub_demo_pro",
            messages=messages,
            mode=api_request.mode,
            stream=True,
        )
        try:
            return await run_pipeline(request, emit=emit_stage)
        finally:
            await stage_queue.put(None)

    yield _sse(
        "conversation",
        {
            "conversation_id": conversation["id"],
            "user_message_id": user_message["id"],
            "title": conversation["title"],
        },
    )

    task = asyncio.create_task(execute_pipeline())
    while True:
        stage = await stage_queue.get()
        if stage is None:
            break
        yield _sse(
            "stage",
            {
                "stage": stage.stage,
                "message": stage.message,
                "data": stage.data,
            },
        )

    response = await task
    latency_ms = int((time.perf_counter() - started) * 1000)
    served_by = _served_by(api_request.mode, response)
    tokens = response.route_tokens or _estimate_tokens(response.answer)
    answer = response.answer

    assistant_message: dict[str, object] | None = None
    for token in answer.split():
        yield _sse("token", {"text": f"{token} "})
        await asyncio.sleep(0)

    assistant_message = await store.add_message(
        str(conversation["id"]),
        "assistant",
        answer,
        served_by=served_by,
        tokens=tokens,
        latency_ms=latency_ms,
    )
    yield _sse(
        "done",
        {
            "conversation_id": conversation["id"],
            "message_id": assistant_message["id"],
            "served_by": served_by,
            "tokens": tokens,
            "latency_ms": latency_ms,
            "model": api_request.model,
            "mode": api_request.mode,
        },
    )


@router.post("/chat")
async def post_chat(
    api_request: ChatApiRequest,
    response: Response,
    user: ChatUser = Depends(enforce_chat_rate_limit),
    store: ChatHistoryStore = Depends(get_store),
) -> StreamingResponse:
    message = api_request.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Message is required")

    if api_request.conversation_id:
        conversation = await store.get_conversation(user.user_id, api_request.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = await store.create_conversation(user.user_id, generate_title(message))

    user_message = await store.add_message(
        str(conversation["id"]),
        "user",
        message,
        served_by="user",
        tokens=_estimate_tokens(message),
        latency_ms=0,
    )
    stream = StreamingResponse(
        _stream_chat_turn(
            store=store,
            user=user,
            api_request=api_request.model_copy(update={"message": message}),
            conversation=conversation,
            user_message=user_message,
        ),
        media_type="text/event-stream",
    )
    for header in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
        if header in response.headers:
            stream.headers[header] = response.headers[header]
    return stream


@router.get("/conversations")
async def list_conversations(
    user: ChatUser = Depends(BetaChatUserDep),
    store: ChatHistoryStore = Depends(get_store),
) -> dict[str, object]:
    return {"conversations": await store.list_conversations(user.user_id), "user": user.__dict__}


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    user: ChatUser = Depends(BetaChatUserDep),
    store: ChatHistoryStore = Depends(get_store),
) -> dict[str, object]:
    conversation = await store.get_conversation(user.user_id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "conversation": conversation,
        "messages": await store.list_messages(user.user_id, conversation_id),
    }


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: str,
    body: RenameConversationRequest,
    user: ChatUser = Depends(BetaChatUserDep),
    store: ChatHistoryStore = Depends(get_store),
) -> dict[str, object]:
    conversation = await store.rename_conversation(user.user_id, conversation_id, body.title.strip())
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation": conversation}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: ChatUser = Depends(BetaChatUserDep),
    store: ChatHistoryStore = Depends(get_store),
) -> dict[str, object]:
    deleted = await store.soft_delete_conversation(user.user_id, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True, "undo_window_days": 30}
