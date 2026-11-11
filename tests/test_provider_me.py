"""/api/provider/me: the signed-in provider's own nodes, for the host
dashboard. A provider whose node is already on the mesh goes straight to the
live dashboard instead of the install steps."""
from datetime import timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

import api


class FakeAuth:
    def __init__(self, emails):
        self.emails = emails            # token -> email

    def get_user(self, token):
        if token not in self.emails:
            raise Exception("invalid JWT")
        return SimpleNamespace(user=SimpleNamespace(id="u", email=self.emails[token]))


def _setup(monkeypatch):
    api._rate_buckets.clear()
    store = api.InMemoryProviderStore()
    api.app.dependency_overrides[api.get_provider_store] = lambda: store
    monkeypatch.setattr(api, "get_supabase_client", lambda: SimpleNamespace(auth=FakeAuth({"tok-host": "Host@Example.com", "tok-other": "other@example.com"})))
    return store, TestClient(api.app)


def _node(client, email):
    token = client.post("/api/provider/signup", json={"email": email, "gpu_model": "", "region": ""}).json()["claim_token"]
    return client.post("/api/provider/claim", json={
        "claim_token": token, "hostname": "pc",
        "gpu_info": {"gpu_model": "NVIDIA GeForce RTX 4090", "vram_mib": 24564},
    }).json()


def test_requires_a_signed_in_user(monkeypatch):
    _, client = _setup(monkeypatch)
    assert client.get("/api/provider/me").status_code == 401
    assert client.get("/api/provider/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    api.app.dependency_overrides.clear()


def test_lists_only_my_nodes_with_live_status(monkeypatch):
    store, client = _setup(monkeypatch)
    mine = _node(client, "host@example.com")
    _node(client, "someone@else.com")
    d = client.get("/api/provider/me", headers={"Authorization": "Bearer tok-host"}).json()
    assert d["email"] == "host@example.com"
    assert [n["node_id"] for n in d["nodes"]] == [mine["node_id"]]
    n = d["nodes"][0]
    assert n["status"] == "online" and n["eligible_for_jobs"] is True
    assert n["model_ready"] is False            # nothing advertised yet

    # Heartbeat with the model ready, and some tokens served.
    client.post("/api/node/heartbeat",
                headers={"X-Node-Id": mine["node_id"], "X-Node-Secret": mine["node_secret"]},
                json={"hostname": "pc", "gpu_info": {"gpu_model": "NVIDIA GeForce RTX 4090", "vram_mib": 24564},
                      "models": ["llama3.3:70b-instruct-q4_K_M"]})
    store.providers[mine["node_id"]]["total_tokens_served"] = 2_000_000
    n = client.get("/api/provider/me", headers={"Authorization": "Bearer tok-host"}).json()["nodes"][0]
    assert n["model_ready"] is True
    assert n["tokens_out"] == 2_000_000
    assert abs(n["earnings_usd"] - 1.2) < 1e-9      # 2M tokens at $0.60 per million
    api.app.dependency_overrides.clear()


def test_a_quiet_node_is_offline(monkeypatch):
    store, client = _setup(monkeypatch)
    mine = _node(client, "host@example.com")
    store.providers[mine["node_id"]]["last_seen_at"] = api.isoformat(api.utc_now() - timedelta(minutes=10))
    n = client.get("/api/provider/me", headers={"Authorization": "Bearer tok-host"}).json()["nodes"][0]
    assert n["status"] == "offline" and n["last_beat_ago_s"] >= 600
    api.app.dependency_overrides.clear()


def test_no_nodes_yet(monkeypatch):
    _, client = _setup(monkeypatch)
    d = client.get("/api/provider/me", headers={"Authorization": "Bearer tok-other"}).json()
    assert d["nodes"] == []
    api.app.dependency_overrides.clear()


def test_a_24gb_card_counts_as_24gb():
    # nvidia-smi reports an RTX 4090 as 24564 MiB, a little under 24576.
    assert api.node_meets_requirements({"gpu_model": "NVIDIA GeForce RTX 4090", "vram_mib": 24564})
    assert not api.node_meets_requirements({"gpu_model": "NVIDIA GeForce RTX 4080", "vram_mib": 16376})
