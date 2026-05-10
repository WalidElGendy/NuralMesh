from fastapi.testclient import TestClient

import api


def test_provider_claim_creates_provider_and_credentials():
    store = api.InMemoryProviderStore()
    api.app.dependency_overrides[api.get_provider_store] = lambda: store
    client = TestClient(api.app)

    signup = client.post(
        "/api/provider/signup",
        json={"email": "host@example.com", "gpu_model": "RTX 4090", "region": "US West"},
    )
    assert signup.status_code == 200
    claim_token = signup.json()["claim_token"]

    claim = client.post(
        "/api/provider/claim",
        json={
            "claim_token": claim_token,
            "hostname": "gpu-host-01",
            "gpu_info": {"gpus": ["NVIDIA RTX 4090, 24564 MiB"]},
        },
    )
    assert claim.status_code == 200
    body = claim.json()
    assert body["provider_id"].startswith("prov_")
    assert body["node_id"].startswith("node_")
    assert len(body["node_secret"]) == 64

    heartbeat = client.post(
        "/api/node/heartbeat",
        headers={"X-Node-Id": body["node_id"], "X-Node-Secret": body["node_secret"]},
        json={"hostname": "gpu-host-01", "gpu_info": {"ok": True}},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["status"] == "ok"
    api.app.dependency_overrides.clear()


def test_provider_claim_rejects_reused_token():
    store = api.InMemoryProviderStore()
    api.app.dependency_overrides[api.get_provider_store] = lambda: store
    client = TestClient(api.app)
    token = store.create_claim_token("host@example.com", "RTX 4090", "US West")["claim_token"]
    payload = {"claim_token": token, "hostname": "gpu-host-01", "gpu_info": {}}

    first = client.post("/api/provider/claim", json=payload)
    second = client.post("/api/provider/claim", json=payload)

    assert first.status_code == 200
    assert second.status_code == 400
    assert "claim token" in second.json()["detail"]
    api.app.dependency_overrides.clear()


def test_install_route_serves_shellscript_content_type():
    client = TestClient(api.app)
    response = client.get("/install")

    assert response.status_code == 200
    assert "text/x-shellscript" in response.headers["content-type"]
    assert "MODEL_NAME=\"llama3.3:70b-instruct-q4_K_M\"" in response.text


def test_installer_subdomain_root_serves_shellscript():
    client = TestClient(api.app)
    response = client.get("/", headers={"Host": "install.beta.meshnet.co"})

    assert response.status_code == 200
    assert "text/x-shellscript" in response.headers["content-type"]
