import pytest
from fastapi import HTTPException, Request
from starlette.datastructures import Headers

from app.lib import auth


def make_request(headers: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/chat",
        "headers": Headers(headers or {}).raw,
    }
    return Request(scope)


def test_generate_key_format() -> None:
    key = auth.generate_key()
    assert key.startswith("nm_")
    assert len(key) >= 40


def test_hash_key_deterministic() -> None:
    assert auth.hash_key("nm_example") == auth.hash_key("nm_example")
    assert auth.hash_key("nm_example") != auth.hash_key("nm_other")


@pytest.mark.asyncio
async def test_api_key_dep_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "false")
    record = await auth.ApiKeyDep(make_request({"Authorization": "Bearer anything"}))
    assert record.name == "dev"
    assert record.tier == "admin"


@pytest.mark.asyncio
async def test_api_key_dep_missing_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    with pytest.raises(HTTPException) as exc:
        await auth.ApiKeyDep(make_request())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_api_key_dep_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")

    class RedisMock:
        async def hgetall(self, key: str) -> dict[str, str]:
            return {}

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(auth, "get_redis_client", lambda: RedisMock())
    with pytest.raises(HTTPException) as exc:
        await auth.ApiKeyDep(make_request({"Authorization": "Bearer nm_missing"}))
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid or expired API key"
