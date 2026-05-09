from __future__ import annotations

import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import ChatResponse, StageEvent
from app.lib.chat_history import MemoryChatHistoryStore
from app.routers import chat


class RedisMock:
    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.values: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        value = self.values.get(key)
        return str(value) if value is not None else None

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None

    async def zremrangebyscore(self, key: str, minimum: float, maximum: float) -> None:
        members = self.zsets.setdefault(key, {})
        for member, score in list(members.items()):
            if minimum <= score <= maximum:
                del members[member]

    async def zcard(self, key: str) -> int:
        return len(self.zsets.setdefault(key, {}))

    async def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self.zsets.setdefault(key, {}).update(mapping)


def _done_payload(body: str) -> dict[str, object]:
    for frame in body.split("\n\n"):
        if frame.startswith("event: done"):
            data = frame.split("data: ", 1)[1]
            return json.loads(data)
    raise AssertionError("missing done event")


@pytest.fixture
def chat_fixture(monkeypatch: pytest.MonkeyPatch):
    store = MemoryChatHistoryStore()
    redis = RedisMock()

    async def fake_run_pipeline(request, emit=None):
        if emit:
            await emit(StageEvent(stage="route", message="done"))
        return ChatResponse(
            job_id=f"job_{int(time.time())}",
            answer="Mocked assistant reply.",
            cost_usd=0,
            providers_paid=0,
            route_model="llama-3.3-70b",
            route_tokens=4,
        )

    app.dependency_overrides[chat.get_store] = lambda: store
    monkeypatch.setattr(chat, "get_redis_client", lambda: redis)
    monkeypatch.setattr(chat, "run_pipeline", fake_run_pipeline)
    yield TestClient(app), store, redis, str(uuid4())
    app.dependency_overrides.clear()


def test_chat_sse_creates_conversation_and_persists_messages(chat_fixture) -> None:
    client, store, _redis, user_id = chat_fixture

    with client.stream(
        "POST",
        "/api/chat",
        headers={"X-Beta-User-Id": user_id},
        json={"message": "Hello sovereign mesh", "mode": "auto"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: token" in body
    payload = _done_payload(body)
    assert payload["conversation_id"]
    assert payload["message_id"]
    assert str(payload["served_by"]).startswith("Sovereign")

    conversation_id = str(payload["conversation_id"])
    persisted = store.messages[conversation_id]
    assert [message["role"] for message in persisted] == ["user", "assistant"]
    assert persisted[0]["content"] == "Hello sovereign mesh"
    assert persisted[1]["content"] == "Mocked assistant reply."
    assert persisted[1]["tokens"] == 4


def test_chat_daily_rate_limit_returns_upgrade_message(chat_fixture) -> None:
    client, _store, redis, user_id = chat_fixture
    redis.values[f"ratelimit:chat:{user_id}:daily"] = 200

    response = client.post(
        "/api/chat",
        headers={"X-Beta-User-Id": user_id},
        json={"message": "Will this exceed the daily limit?", "mode": "auto"},
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "You've reached your daily limit. Upgrade to keep chatting."
