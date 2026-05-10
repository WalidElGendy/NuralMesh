from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import api


def set_required_production_env(monkeypatch: pytest.MonkeyPatch) -> None:
    api.get_version.cache_clear()
    monkeypatch.setenv("NM_ENV", "production")
    for name in api.REQUIRED_PRODUCTION_ENV:
        monkeypatch.setenv(name, f"test-{name.lower()}")


def test_health_returns_version_and_production_env(monkeypatch: pytest.MonkeyPatch) -> None:
    set_required_production_env(monkeypatch)
    monkeypatch.setenv("GIT_SHA", "abcdef1234567890")

    with TestClient(api.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "abcdef123456",
        "env": "production",
    }


def test_startup_fails_fast_when_production_env_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NM_ENV", "production")
    monkeypatch.delenv("SUPABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="Missing required env vars"):
        with TestClient(api.app):
            pass


def test_readyz_returns_ok_when_dependencies_are_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_required_production_env(monkeypatch)

    with (
        patch("api.check_supabase", return_value=None),
        patch("api.check_redis", new=AsyncMock(return_value=None)),
        patch("api.check_qdrant", new=AsyncMock(return_value=None)),
        TestClient(api.app) as client,
    ):
        response = client.get("/readyz")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["checks"] == {
        "supabase": {"status": "ok"},
        "redis": {"status": "ok"},
        "qdrant": {"status": "ok"},
    }


def test_readyz_returns_503_when_a_dependency_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_required_production_env(monkeypatch)

    with (
        patch("api.check_supabase", return_value=None),
        patch("api.check_redis", new=AsyncMock(side_effect=RuntimeError("redis down"))),
        patch("api.check_qdrant", new=AsyncMock(return_value=None)),
        TestClient(api.app) as client,
    ):
        response = client.get("/readyz")

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "degraded"
    assert body["checks"]["redis"]["status"] == "error"
    assert "redis down" in body["checks"]["redis"]["detail"]
