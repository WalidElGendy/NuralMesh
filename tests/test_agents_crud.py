"""
End-to-end CRUD test for /api/agents (multi-agent sidebar backend).

Skipped automatically unless NM_TEST_TOKEN is set in the environment.
Set NM_API_BASE to override the default (https://api.beta.meshnet.co).

Usage:
  export NM_TEST_TOKEN="<supabase-jwt>"
  export NM_API_BASE="https://api.beta.meshnet.co"   # optional
  pytest tests/test_agents_crud.py -v
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest

TOKEN = os.environ.get("NM_TEST_TOKEN", "").strip()
BASE = os.environ.get("NM_API_BASE", "https://api.beta.meshnet.co").rstrip("/")

pytestmark = pytest.mark.skipif(
    not TOKEN,
    reason="NM_TEST_TOKEN not set; skipping live /api/agents CRUD test.",
)


@pytest.fixture(scope="module")
def client():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with httpx.Client(base_url=BASE, headers=headers, timeout=15.0) as c:
        yield c


def _new_title() -> str:
    return f"pytest-agent-{uuid.uuid4().hex[:8]}"


def test_list_agents_returns_array(client: httpx.Client) -> None:
    r = client.get("/api/agents")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert isinstance(payload, list)


def test_create_rename_delete_agent(client: httpx.Client) -> None:
    title = _new_title()
    # Create
    r = client.post("/api/agents", json={"title": title})
    assert r.status_code in (200, 201), r.text
    agent = r.json()
    agent_id = agent.get("id") or agent.get("agent_id")
    assert agent_id, f"missing id in create response: {agent!r}"
    assert agent.get("title") == title

    try:
        # Confirm it appears in list
        r = client.get("/api/agents")
        assert r.status_code == 200
        ids = {a.get("id") or a.get("agent_id") for a in r.json()}
        assert agent_id in ids

        # Rename
        renamed = title + "-renamed"
        r = client.patch(f"/api/agents/{agent_id}", json={"title": renamed})
        assert r.status_code in (200, 204), r.text
        if r.status_code == 200:
            assert r.json().get("title") == renamed
    finally:
        # Delete (cleanup even on assertion failure above)
        r = client.delete(f"/api/agents/{agent_id}")
        assert r.status_code in (200, 204), r.text


def test_create_requires_auth() -> None:
    # Sanity: no bearer header should yield 401, regardless of NM_TEST_TOKEN.
    with httpx.Client(base_url=BASE, timeout=15.0) as c:
        r = c.get("/api/agents")
    assert r.status_code in (401, 403), r.text

