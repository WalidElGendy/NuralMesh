"""
Signing a user in must never change the server's own Supabase connection.

supabase-py swaps a client's Authorization header for the user's access token
when that client signs someone in. /api/auth/login used to sign in on the
shared service-role client, so after the first login every database call in the
process ran as that user and failed with "permission denied for table
conversations". These tests run offline: no network, no real keys.

  pytest tests/test_auth_client_isolation.py -v
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "anon-key")

import api  # noqa: E402
from supabase_auth import SyncGoTrueClient  # noqa: E402


def _auth_header(client) -> str:
    return client.options.headers.get("Authorization", "")


def _fake_sign_in(self, credentials):
    """What a successful password sign-in does inside supabase-py: tell the
    client's listeners SIGNED_IN with the user's session, then return it."""
    session = SimpleNamespace(access_token="user-access-token", refresh_token="r", expires_at=0)
    user = SimpleNamespace(id="u1", email=credentials["email"], user_metadata={})
    self._notify_all_subscribers("SIGNED_IN", session)
    return SimpleNamespace(session=session, user=user)


def test_sign_in_on_a_client_does_swap_its_header():
    """The library behaviour the fix guards against, so a future upgrade that
    changes it is noticed rather than assumed."""
    c = api.get_auth_client()
    before = _auth_header(c)
    c.auth._notify_all_subscribers("SIGNED_IN", SimpleNamespace(access_token="user-access-token"))
    assert _auth_header(c) != before
    assert "user-access-token" in _auth_header(c)


def test_auth_client_is_not_the_shared_client():
    assert api.get_auth_client() is not api.get_supabase_client()
    assert api.get_auth_client() is not api.get_auth_client()


def test_login_keeps_the_shared_client_on_the_service_role_key(monkeypatch):
    shared = api.get_supabase_client()
    before = _auth_header(shared)
    assert "service-role-key" in before

    monkeypatch.setattr(SyncGoTrueClient, "sign_in_with_password", _fake_sign_in)
    res = api.auth_login(api.AuthLoginRequest(email="someone@example.com", password="x"))

    assert res.access_token == "user-access-token"
    assert _auth_header(shared) == before, "login leaked the user's token into the shared client"
    assert api.get_supabase_client() is shared


def test_magic_link_does_not_touch_the_shared_client(monkeypatch):
    shared = api.get_supabase_client()
    before = _auth_header(shared)
    used = []
    monkeypatch.setattr(SyncGoTrueClient, "sign_in_with_otp", lambda self, creds: used.append(self))
    api.auth_magic_link(api.MagicLinkRequest(email="someone@example.com"))
    assert used and used[0] is not shared.auth
    assert _auth_header(shared) == before


def test_auth_client_uses_the_service_key_not_the_anon_key(monkeypatch):
    """SUPABASE_ANON_KEY on the server was not a valid key for the project,
    and preferring it made every password sign-in fail."""
    monkeypatch.setenv("SUPABASE_ANON_KEY", "stale-anon-key")
    c = api.get_auth_client()
    assert "service-role-key" in c.supabase_key
    assert "stale-anon-key" not in c.supabase_key


def test_a_rejected_api_key_is_not_reported_as_a_wrong_password(monkeypatch):
    def refuse(self, credentials):
        raise Exception("Invalid API key")
    monkeypatch.setattr(SyncGoTrueClient, "sign_in_with_password", refuse)
    import pytest
    with pytest.raises(api.HTTPException) as e:
        api.auth_login(api.AuthLoginRequest(email="someone@example.com", password="x"))
    assert e.value.status_code == 502 and e.value.detail == "auth_provider_error"
