from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import (
    BETA_INVITES_TABLE,
    BETA_PROVIDER_TERMS_VERSION,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _new_invite_code() -> str:
    return "NM-" + secrets.token_urlsafe(9).replace("_", "").replace("-", "").upper()[:10]


class SupabaseBetaStore:
    """Small PostgREST wrapper for beta profiles, providers, and invites."""

    def __init__(self) -> None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        self.base_url = SUPABASE_URL.rstrip("/")
        self.headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: Any | None = None,
        prefer: str | None = "return=representation",
    ) -> Any:
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(
                method,
                f"{self.base_url}/rest/v1/{path}",
                params=params,
                json=json,
                headers=headers,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Supabase {method} {path} failed: {response.text[:300]}")
        if not response.content:
            return None
        return response.json()

    async def create_profile(self, user_id: str, email: str, intent: str, invite_code: str | None) -> dict[str, Any]:
        role = "provider" if intent == "provider" else "user"
        profile = {
            "id": user_id,
            "email": email,
            "role": role,
            "subscription_status": "none",
            "trial_started_at": iso_now(),
            "trial_request_count": 0,
            "invite_code_used": invite_code,
        }
        result = await self._request("POST", "users", json=profile, prefer="resolution=merge-duplicates,return=representation")
        if role == "provider":
            await self._request(
                "POST",
                "providers",
                json={"user_id": user_id, "status": "pending_terms"},
                prefer="resolution=merge-duplicates,return=representation",
            )
        return result[0] if isinstance(result, list) and result else profile

    async def get_profile(self, user_id: str) -> dict[str, Any] | None:
        rows = await self._request(
            "GET",
            "users",
            params={"select": "*", "id": f"eq.{user_id}", "limit": "1"},
            prefer=None,
        )
        return rows[0] if rows else None

    async def get_provider(self, user_id: str) -> dict[str, Any] | None:
        rows = await self._request(
            "GET",
            "providers",
            params={"select": "*", "user_id": f"eq.{user_id}", "limit": "1"},
            prefer=None,
        )
        return rows[0] if rows else None

    async def update_user(self, user_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        rows = await self._request(
            "PATCH",
            "users",
            params={"id": f"eq.{user_id}"},
            json=values,
        )
        return rows[0] if rows else None

    async def update_user_by_customer(self, customer_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        rows = await self._request(
            "PATCH",
            "users",
            params={"stripe_customer_id": f"eq.{customer_id}"},
            json=values,
        )
        return rows[0] if rows else None

    async def accept_provider_terms(
        self,
        user_id: str,
        terms_version: str = BETA_PROVIDER_TERMS_VERSION,
    ) -> dict[str, Any]:
        rows = await self._request(
            "PATCH",
            "providers",
            params={"user_id": f"eq.{user_id}"},
            json={
                "status": "terms_accepted",
                "accepted_terms_at": iso_now(),
                "accepted_terms_version": terms_version,
            },
        )
        return rows[0] if rows else {}

    async def get_user_invites(self, user_id: str) -> list[dict[str, Any]]:
        rows = await self._request(
            "GET",
            BETA_INVITES_TABLE,
            params={
                "select": "code,status,claimed_at,claimed_by_user_id,parent_code,created_at",
                "created_by_user_id": f"eq.{user_id}",
                "order": "created_at.asc",
            },
            prefer=None,
        )
        return rows or []

    async def claim_invite_and_mint_children(self, code: str, user_id: str) -> list[dict[str, Any]]:
        code = code.strip()
        rows = await self._request(
            "GET",
            BETA_INVITES_TABLE,
            params={"select": "*", "code": f"eq.{code}", "limit": "1"},
            prefer=None,
        )
        if not rows:
            raise ValueError("Invalid invite code")
        invite = rows[0]
        if invite.get("claimed_by_user_id") or invite.get("status") == "claimed":
            raise ValueError("Invite code has already been claimed")
        await self._request(
            "PATCH",
            BETA_INVITES_TABLE,
            params={"code": f"eq.{code}"},
            json={"status": "claimed", "claimed_by_user_id": user_id, "claimed_at": iso_now()},
        )
        children = [
            {
                "code": _new_invite_code(),
                "parent_code": code,
                "created_by_user_id": user_id,
                "status": "unclaimed",
            }
            for _ in range(5)
        ]
        return await self._request("POST", BETA_INVITES_TABLE, json=children) or []

    async def seed_root_invites(self, count: int, created_by: str = "admin") -> list[dict[str, Any]]:
        rows = [
            {
                "code": _new_invite_code(),
                "created_by_user_id": created_by,
                "status": "unclaimed",
            }
            for _ in range(count)
        ]
        return await self._request("POST", BETA_INVITES_TABLE, json=rows) or []

    async def increment_trial_usage(self, user_id: str) -> dict[str, Any]:
        profile = await self.get_profile(user_id)
        if not profile:
            raise ValueError("User profile not found")
        count = int(profile.get("trial_request_count") or 0) + 1
        await self.update_user(user_id, {"trial_request_count": count})
        profile["trial_request_count"] = count
        return profile


class InMemoryBetaStore:
    """Deterministic local store used by tests and development without Supabase."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.providers: dict[str, dict[str, Any]] = {}
        self.invites: dict[str, dict[str, Any]] = {
            "ROOT-BETA": {
                "code": "ROOT-BETA",
                "created_by_user_id": "admin",
                "status": "unclaimed",
                "created_at": iso_now(),
            }
        }

    async def create_profile(self, user_id: str, email: str, intent: str, invite_code: str | None) -> dict[str, Any]:
        role = "provider" if intent == "provider" else "user"
        profile = {
            "id": user_id,
            "email": email,
            "role": role,
            "subscription_status": "none",
            "trial_started_at": iso_now(),
            "trial_request_count": 0,
            "invite_code_used": invite_code,
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
            "subscription_current_period_end": None,
        }
        self.users[user_id] = profile
        if role == "provider":
            self.providers[user_id] = {"user_id": user_id, "status": "pending_terms"}
        return profile

    async def get_profile(self, user_id: str) -> dict[str, Any] | None:
        return self.users.get(user_id)

    async def get_provider(self, user_id: str) -> dict[str, Any] | None:
        return self.providers.get(user_id)

    async def update_user(self, user_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        if user_id not in self.users:
            return None
        self.users[user_id].update(values)
        return self.users[user_id]

    async def update_user_by_customer(self, customer_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        for profile in self.users.values():
            if profile.get("stripe_customer_id") == customer_id:
                profile.update(values)
                return profile
        return None

    async def accept_provider_terms(self, user_id: str, terms_version: str = BETA_PROVIDER_TERMS_VERSION) -> dict[str, Any]:
        provider = self.providers.setdefault(user_id, {"user_id": user_id})
        provider.update(
            {
                "status": "terms_accepted",
                "accepted_terms_at": iso_now(),
                "accepted_terms_version": terms_version,
            }
        )
        return provider

    async def get_user_invites(self, user_id: str) -> list[dict[str, Any]]:
        return [invite for invite in self.invites.values() if invite.get("created_by_user_id") == user_id]

    async def claim_invite_and_mint_children(self, code: str, user_id: str) -> list[dict[str, Any]]:
        invite = self.invites.get(code.strip())
        if not invite:
            raise ValueError("Invalid invite code")
        if invite.get("claimed_by_user_id") or invite.get("status") == "claimed":
            raise ValueError("Invite code has already been claimed")
        invite.update({"status": "claimed", "claimed_by_user_id": user_id, "claimed_at": iso_now()})
        children = []
        for _ in range(5):
            child = {
                "code": _new_invite_code(),
                "parent_code": code.strip(),
                "created_by_user_id": user_id,
                "status": "unclaimed",
                "created_at": iso_now(),
            }
            self.invites[child["code"]] = child
            children.append(child)
        return children

    async def seed_root_invites(self, count: int, created_by: str = "admin") -> list[dict[str, Any]]:
        rows = []
        for _ in range(count):
            row = {
                "code": _new_invite_code(),
                "created_by_user_id": created_by,
                "status": "unclaimed",
                "created_at": iso_now(),
            }
            self.invites[row["code"]] = row
            rows.append(row)
        return rows

    async def increment_trial_usage(self, user_id: str) -> dict[str, Any]:
        profile = self.users[user_id]
        profile["trial_request_count"] = int(profile.get("trial_request_count") or 0) + 1
        return profile


_memory_store = InMemoryBetaStore()


def get_beta_store() -> SupabaseBetaStore | InMemoryBetaStore:
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseBetaStore()
    return _memory_store


def trial_is_active(profile: dict[str, Any]) -> bool:
    started = profile.get("trial_started_at")
    if not started:
        return True
    try:
        started_at = datetime.fromisoformat(_as_text(started).replace("Z", "+00:00"))
    except ValueError:
        return False
    return utc_now() < started_at + timedelta(days=7)

