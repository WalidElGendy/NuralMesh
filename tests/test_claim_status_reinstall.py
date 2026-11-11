"""The host dashboard waits on /api/provider/claim-status for the code baked
into the installer. Re-running the installer on a machine that already has a
node keeps its old credentials and never redeems the new code, so the page
waited forever. A node of the same account that checks in after the code was
issued now counts.
"""
from datetime import timedelta

from fastapi.testclient import TestClient

import api


def _client(store):
    api._rate_buckets.clear()              # signups are rate-limited per IP
    api.app.dependency_overrides[api.get_provider_store] = lambda: store
    return TestClient(api.app)


def _signup(client, email):
    r = client.post("/api/provider/signup", json={"email": email, "gpu_model": "", "region": ""})
    assert r.status_code == 200
    return r.json()["claim_token"]


def _claim(client, token):
    r = client.post("/api/provider/claim", json={"claim_token": token, "hostname": "pc", "gpu_info": {}})
    assert r.status_code == 200
    return r.json()


def _beat(client, creds):
    r = client.post(
        "/api/node/heartbeat",
        headers={"X-Node-Id": creds["node_id"], "X-Node-Secret": creds["node_secret"]},
        json={"hostname": "pc", "gpu_info": {}},
    )
    assert r.status_code == 200


def test_redeemed_code_reports_its_node():
    store = api.InMemoryProviderStore()
    client = _client(store)
    creds = _claim(client, _signup(client, "host@example.com"))
    d = client.get("/api/provider/claim-status", params={"claim_token": next(iter(store.claim_tokens))}).json()
    assert d["claimed"] and d["node_id"] == creds["node_id"]
    api.app.dependency_overrides.clear()


def test_reinstall_with_existing_node_counts_once_it_checks_in():
    store = api.InMemoryProviderStore()
    client = _client(store)
    old = _claim(client, _signup(client, "host@example.com"))
    # The old node went quiet long ago.
    store.providers[old["node_id"]]["last_seen_at"] = api.isoformat(api.utc_now() - timedelta(days=30))

    fresh = _signup(client, "host@example.com")
    assert client.get("/api/provider/claim-status", params={"claim_token": fresh}).json() == {"claimed": False}

    _beat(client, old)                     # the installer skipped the claim and the old node checked in
    d = client.get("/api/provider/claim-status", params={"claim_token": fresh}).json()
    assert d["claimed"] and d["node_id"] == old["node_id"]
    api.app.dependency_overrides.clear()


def test_another_accounts_node_does_not_count():
    store = api.InMemoryProviderStore()
    client = _client(store)
    other = _claim(client, _signup(client, "someone@example.com"))
    mine = _signup(client, "host@example.com")
    _beat(client, other)
    assert client.get("/api/provider/claim-status", params={"claim_token": mine}).json() == {"claimed": False}
    api.app.dependency_overrides.clear()
