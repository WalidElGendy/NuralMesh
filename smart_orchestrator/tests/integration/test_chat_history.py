from __future__ import annotations

import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import ChatResponse
from app.lib.chat_history import MemoryChatHistoryStore
from app.routers import chat
from tests.integration.test_chat_endpoints import RedisMock


@pytest.fixture
def history_fixture(monkeypatch: pytest.MonkeyPatch):
    store = MemoryChatHistoryStore()
    redis = RedisMock()

    async def fake_run_pipeline(request, emit=None):
        return ChatResponse(
            job_id=f"job_{int(time.time())}",
            answer="History reply.",
            cost_usd=0,
            providers_paid=0,
            route_model="llama-3.3-70b",
            route_tokens=2,
        )

    app.dependency_overrides[chat.get_store] = lambda: store
    monkeypatch.setattr(chat, "get_redis_client", lambda: redis)
    monkeypatch.setattr(chat, "run_pipeline", fake_run_pipeline)
    yield TestClient(app), str(uuid4())
    app.dependency_overrides.clear()


def _create_conversation(client: TestClient, user_id: str) -> str:
    with client.stream(
        "POST",
        "/api/chat",
        headers={"X-Beta-User-Id": user_id},
        json={"message": "Name this thread from the first prompt"},
    ) as response:
        assert response.status_code == 200
        assert "event: done" in "".join(response.iter_text())
    payload = client.get("/api/conversations", headers={"X-Beta-User-Id": user_id}).json()
    return payload["conversations"][0]["id"]


def test_list_rename_and_delete_conversations(history_fixture) -> None:
    client, user_id = history_fixture
    conversation_id = _create_conversation(client, user_id)

    listed = client.get("/api/conversations", headers={"X-Beta-User-Id": user_id})
    assert listed.status_code == 200
    assert listed.json()["conversations"][0]["title"] == "Name this thread from the first prompt"

    renamed = client.patch(
        f"/api/conversations/{conversation_id}",
        headers={"X-Beta-User-Id": user_id},
        json={"title": "Renamed beta chat"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["conversation"]["title"] == "Renamed beta chat"

    deleted = client.delete(
        f"/api/conversations/{conversation_id}",
        headers={"X-Beta-User-Id": user_id},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "undo_window_days": 30}

    listed_after_delete = client.get("/api/conversations", headers={"X-Beta-User-Id": user_id})
    assert listed_after_delete.status_code == 200
    assert listed_after_delete.json()["conversations"] == []
