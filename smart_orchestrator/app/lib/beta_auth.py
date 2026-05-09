from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, Request, Response

from app.config import (
    APP_BASE_URL,
    COOKIE_SECURE,
    CSRF_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
)


@dataclass
class SessionUser:
    id: str
    email: str
    role: str = "user"
    user_metadata: dict[str, Any] | None = None


def _cookie_options() -> dict[str, Any]:
    return {"httponly": True, "secure": COOKIE_SECURE, "samesite": "lax", "path": "/"}


def set_session_cookies(response: Response, access_token: str, refresh_token: str | None = None) -> str:
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(SESSION_COOKIE_NAME, access_token, max_age=60 * 60 * 24 * 7, **_cookie_options())
    if refresh_token:
        response.set_cookie(
            REFRESH_COOKIE_NAME,
            refresh_token,
            max_age=60 * 60 * 24 * 30,
            **_cookie_options(),
        )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=60 * 60 * 24 * 7,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return csrf_token


def clear_session_cookies(response: Response) -> None:
    for name in (SESSION_COOKIE_NAME, REFRESH_COOKIE_NAME, CSRF_COOKIE_NAME):
        response.delete_cookie(name, path="/")


async def require_csrf(request: Request) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get("x-csrf-token")
    if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def _redirect_for_intent(intent: str) -> str:
    return "/host/setup" if intent == "provider" else "/chat"


class SupabaseAuthClient:
    """Supabase Auth REST client used by the beta web session flow."""

    def __init__(self) -> None:
        if not SUPABASE_URL or not SUPABASE_ANON_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required")
        self.base_url = SUPABASE_URL.rstrip("/")
        self.anon_headers = {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"}

    async def signup(self, email: str, password: str, intent: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.base_url}/auth/v1/signup",
                headers=self.anon_headers,
                json={
                    "email": email,
                    "password": password,
                    "options": {
                        "email_redirect_to": f"{APP_BASE_URL}/api/auth/confirm",
                        "data": {"intent": intent, "post_confirm_path": _redirect_for_intent(intent)},
                    },
                },
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=400, detail=response.text[:300])
        return response.json()

    async def login_with_password(self, email: str, password: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.base_url}/auth/v1/token?grant_type=password",
                headers=self.anon_headers,
                json={"email": email, "password": password},
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        return response.json()

    async def send_magic_link(self, email: str) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.base_url}/auth/v1/otp",
                headers=self.anon_headers,
                json={
                    "email": email,
                    "type": "magiclink",
                    "options": {"email_redirect_to": f"{APP_BASE_URL}/api/auth/confirm"},
                },
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=400, detail=response.text[:300])

    async def verify_token_hash(self, token_hash: str, verify_type: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.base_url}/auth/v1/verify",
                headers=self.anon_headers,
                json={"token_hash": token_hash, "type": verify_type},
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=400, detail="Invalid or expired confirmation link")
        return response.json()

    async def get_user(self, access_token: str) -> SessionUser:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self.base_url}/auth/v1/user",
                headers={**self.anon_headers, "Authorization": f"Bearer {access_token}"},
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        user = response.json()
        metadata = user.get("user_metadata") or {}
        return SessionUser(
            id=user["id"],
            email=user.get("email") or "",
            role="provider" if metadata.get("intent") == "provider" else "user",
            user_metadata=metadata,
        )


class MockSupabaseAuthClient:
    """Local Supabase Auth stand-in for integration tests without real Supabase secrets."""

    def __init__(self) -> None:
        self.users_by_email: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, str] = {}
        self.confirm_tokens: dict[str, str] = {}

    async def signup(self, email: str, password: str, intent: str) -> dict[str, Any]:
        user_id = f"user_{secrets.token_hex(8)}"
        token = secrets.token_urlsafe(24)
        self.users_by_email[email] = {
            "id": user_id,
            "email": email,
            "password": password,
            "confirmed": False,
            "user_metadata": {"intent": intent, "post_confirm_path": _redirect_for_intent(intent)},
        }
        self.confirm_tokens[token] = email
        return {
            "user": {"id": user_id, "email": email, "user_metadata": self.users_by_email[email]["user_metadata"]},
            "confirmation_url": f"{APP_BASE_URL}/api/auth/confirm?token_hash={token}&type=email",
        }

    async def login_with_password(self, email: str, password: str) -> dict[str, Any]:
        user = self.users_by_email.get(email)
        if not user or user["password"] != password or not user["confirmed"]:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        access = f"mock_access_{secrets.token_urlsafe(24)}"
        refresh = f"mock_refresh_{secrets.token_urlsafe(24)}"
        self.tokens[access] = email
        return {
            "access_token": access,
            "refresh_token": refresh,
            "user": {"id": user["id"], "email": email, "user_metadata": user["user_metadata"]},
        }

    async def send_magic_link(self, email: str) -> None:
        if email not in self.users_by_email:
            raise HTTPException(status_code=404, detail="User not found")

    async def verify_token_hash(self, token_hash: str, verify_type: str) -> dict[str, Any]:
        email = self.confirm_tokens.get(token_hash)
        if verify_type not in {"email", "magiclink"} or not email:
            raise HTTPException(status_code=400, detail="Invalid or expired confirmation link")
        self.users_by_email[email]["confirmed"] = True
        return await self.login_with_password(email, self.users_by_email[email]["password"])

    async def get_user(self, access_token: str) -> SessionUser:
        email = self.tokens.get(access_token)
        if not email:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        user = self.users_by_email[email]
        metadata = user.get("user_metadata") or {}
        return SessionUser(
            id=user["id"],
            email=email,
            role="provider" if metadata.get("intent") == "provider" else "user",
            user_metadata=metadata,
        )


_mock_auth_client = MockSupabaseAuthClient()


def get_auth_client() -> SupabaseAuthClient | MockSupabaseAuthClient:
    if SUPABASE_URL and SUPABASE_ANON_KEY:
        return SupabaseAuthClient()
    return _mock_auth_client


async def current_session_user(request: Request) -> SessionUser:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    authorization = request.headers.get("authorization", "")
    if not token and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await get_auth_client().get_user(token)

