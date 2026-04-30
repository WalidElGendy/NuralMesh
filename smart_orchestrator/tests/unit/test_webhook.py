"""Tests for app/routers/webhook.py - Sprint 6"""
from __future__ import annotations
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
import os
os.environ["AUTH_ENABLED"] = "false"
os.environ["OTEL_ENABLED"] = "false"
os.environ["LOKI_ENABLED"] = "false"

from app.main import app

client = TestClient(app)


def test_webhook_invalid_signature():
    with patch("app.routers.webhook.verify_stripe_signature") as mock_verify:
        from fastapi import HTTPException
        mock_verify.side_effect = HTTPException(status_code=400, detail="Invalid Stripe signature")
        resp = client.post(
            "/webhook/stripe",
            content=b"payload",
            headers={"stripe-signature": "invalid_sig"},
        )
    assert resp.status_code == 400


def test_webhook_missing_signature_header():
    resp = client.post(
        "/webhook/stripe",
        content=b"payload",
    )
    assert resp.status_code == 400


def test_webhook_unknown_event():
    with patch("app.routers.webhook.verify_stripe_signature") as mock_verify:
        mock_verify.return_value = {"type": "payment_intent.created", "data": {"object": {}}}
        resp = client.post(
            "/webhook/stripe",
            content=b"payload",
            headers={"stripe-signature": "t=123,v1=abc"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["received"] is True
    assert data["action"] == "ignored"


def test_webhook_subscription_created():
    with patch("app.routers.webhook.verify_stripe_signature") as mock_verify, \
         patch("app.routers.webhook.handle_subscription_event", new_callable=AsyncMock) as mock_handle, \
         patch("app.routers.webhook.get_redis_client", new_callable=AsyncMock) as mock_redis:
        mock_verify.return_value = {
            "type": "customer.subscription.created",
            "data": {"object": {"customer": "cus_123", "items": {"data": []}}}
        }
        mock_handle.return_value = "upgraded"
        mock_redis.return_value = AsyncMock()
        resp = client.post(
            "/webhook/stripe",
            content=b"payload",
            headers={"stripe-signature": "t=123,v1=abc"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["received"] is True
    assert data["action"] == "upgraded"
