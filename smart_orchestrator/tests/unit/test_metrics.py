"""Tests for Prometheus metrics module and /prometheus endpoint (Sprint 9)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.lib.metrics import (
    record_request,
    record_tokens,
    record_latency,
    record_error,
    REQUESTS_TOTAL,
    TOKENS_TOTAL,
)


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# test_prometheus_endpoint_returns_200
# ---------------------------------------------------------------------------
def test_prometheus_endpoint_returns_200(client):
    resp = client.get("/prometheus")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# test_prometheus_endpoint_content_type
# ---------------------------------------------------------------------------
def test_prometheus_endpoint_content_type(client):
    resp = client.get("/prometheus")
    assert "text/plain" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# test_record_request_increments_counter
# ---------------------------------------------------------------------------
def test_record_request_increments_counter():
    before = REQUESTS_TOTAL.labels(
        endpoint="test_ep", tier="free", category="chat", status="ok"
    )._value.get()
    record_request("test_ep", "free", "chat", "ok")
    after = REQUESTS_TOTAL.labels(
        endpoint="test_ep", tier="free", category="chat", status="ok"
    )._value.get()
    assert after == before + 1


# ---------------------------------------------------------------------------
# test_record_tokens_increments_counter
# ---------------------------------------------------------------------------
def test_record_tokens_increments_counter():
    before = TOKENS_TOTAL.labels(tier="pro", model="llama-3.1-8b")._value.get()
    record_tokens("pro", "llama-3.1-8b", 42)
    after = TOKENS_TOTAL.labels(tier="pro", model="llama-3.1-8b")._value.get()
    assert after == before + 42
