from __future__ import annotations

from urllib.parse import urlparse

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _seed_invite() -> str:
    response = client.post(
        "/api/admin/seed-invites",
        headers={"X-Admin-Secret": "change-me-in-prod"},
        json={"count": 1, "created_by": "test"},
    )
    assert response.status_code == 200
    return response.json()["invites"][0]["code"]


def test_signup_confirm_login_me_returns_none_subscription():
    email = "signup-login@example.com"
    password = "correct horse battery"
    invite_code = _seed_invite()

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
            "invite_code": invite_code,
            "intent": "user",
        },
    )
    assert signup.status_code == 200
    confirmation_url = signup.json()["confirmation_url"]
    assert confirmation_url

    confirm_path = urlparse(confirmation_url).path + "?" + urlparse(confirmation_url).query
    confirm = client.get(confirm_path, follow_redirects=False)
    assert confirm.status_code == 303
    assert confirm.headers["location"] == "/chat"

    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200

    me = client.get("/api/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == email
    assert body["subscription_status"] == "none"
    assert len(body["invites"]) == 5

