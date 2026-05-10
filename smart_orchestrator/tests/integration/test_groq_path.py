import fakeredis.aioredis as fakeredis
from fastapi.testclient import TestClient

from app.lib.groq_client import GroqCompletion
from app.main import app


def test_api_submit_groq_path_persists_served_by(monkeypatch):
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setattr("app.routers.jobs.get_redis_client", lambda: redis)

    async def fake_complete_chat(messages, *, user_id):
        return GroqCompletion(
            content="mocked groq answer",
            model="llama-3.3-70b-versatile",
            prompt_tokens=12,
            completion_tokens=8,
            latency_ms=42,
        )

    monkeypatch.setattr("app.routers.jobs.groq_client.complete_chat", fake_complete_chat)
    client = TestClient(app)

    submit = client.post(
        "/api/submit",
        headers={"x-api-key": "dev-key"},
        json={"prompt": "Answer quickly", "mode": "fast"},
    )
    assert submit.status_code == 200
    job_id = submit.json()["job_id"]
    assert submit.json()["served_by"] == "groq"

    result = client.get(f"/api/{job_id}", headers={"x-api-key": "dev-key"})
    assert result.status_code == 200
    payload = result.json()
    assert payload["status"] == "done"
    assert payload["result"] == "mocked groq answer"
    assert payload["served_by"] == "groq"
    assert payload["tokens"] == 20
