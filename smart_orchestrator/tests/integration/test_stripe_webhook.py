from __future__ import annotations

from unittest.mock import patch
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _signed_up_user() -> str:
    invite = client.post(
        "/api/admin/seed-invites",
        headers={"X-Admin-Secret": "change-me-in-prod"},
        json={"count": 1, "created_by": "webhook-test"},
    ).json()["invites"][0]["code"]
    signup = client.post(
        "/api/auth/signup",
        json={
            "email": "stripe-webhook@example.com",
            "password": "correct horse battery",
            "invite_code": invite,
            "intent": "user",
        },
    )
    confirmation_url = signup.json()["confirmation_url"]
    confirm_path = urlparse(confirmation_url).path + "?" + urlparse(confirmation_url).query
    client.get(confirm_path, follow_redirects=False)
    return client.get("/api/me").json()["id"]


def test_checkout_completed_updates_subscription_status():
    user_id = _signed_up_user()
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": user_id,
                "customer": "cus_beta_test",
                "subscription": "sub_beta_test",
                "metadata": {"user_id": user_id},
            }
        },
    }

    with patch("app.routers.webhook.verify_stripe_signature", return_value=event):
        response = client.post(
            "/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "t=123,v1=abc"},
        )

    assert response.status_code == 200
    assert response.json()["action"] == "subscription_active"
    assert client.get("/api/me").json()["subscription_status"] == "active"

