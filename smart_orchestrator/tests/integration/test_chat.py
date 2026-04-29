from fastapi.testclient import TestClient

from app.main import app


def test_chat_stream_returns_done_event():
    """Ensure /chat streams a final done event for a valid mock subscriber."""
    client = TestClient(app)
    with client.stream(
        "POST",
        "/chat",
        json={
            "subscriber_id": "sub_demo_pro",
            "messages": [{"role": "user", "content": "Explain vector databases for AI search."}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())
    assert response.status_code == 200
    assert "event: done" in body
