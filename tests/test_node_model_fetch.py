"""The node agent must come online before its model is downloaded.

It used to exit when the ~40 GB model was missing, so a fresh install never
checked in. Now it heartbeats straight away, advertises only the models it
really has, takes no jobs until one is ready, and pulls the rest in the
background.
"""
import types

import pytest

import node


class FakeProc:
    def __init__(self, code=None):
        self.returncode = code

    def poll(self):
        return self.returncode


def test_startup_check_no_longer_exits(monkeypatch):
    monkeypatch.setattr(node.ollama, "list", lambda: {"models": []})
    node.startup_self_check()          # used to raise SystemExit(1)


def test_installed_models_is_empty_when_ollama_is_missing(monkeypatch):
    def boom():
        raise ConnectionError("ollama not running")
    monkeypatch.setattr(node.ollama, "list", boom)
    assert node.installed_models() == []


def test_installed_models_reports_what_is_pulled(monkeypatch):
    monkeypatch.setattr(node, "NODE_MODELS", ["a:1", "b:2"])
    monkeypatch.setattr(node.ollama, "list", lambda: {"models": [{"name": "b:2"}, {"name": "x"}]})
    assert node.installed_models() == ["b:2"]


def test_fetcher_waits_for_ollama_then_pulls_once(monkeypatch):
    monkeypatch.setattr(node, "NODE_MODELS", ["m:1"])
    started = []
    monkeypatch.setattr(node.subprocess, "Popen", lambda args, **kw: started.append(args) or FakeProc())
    f = node.ModelFetcher()

    monkeypatch.setattr(node, "find_ollama", lambda: None)
    assert f.tick([]) == "waiting_for_ollama"
    assert started == []

    f.last_try = 0.0                      # allow an immediate retry
    monkeypatch.setattr(node, "find_ollama", lambda: "/usr/bin/ollama")
    assert f.tick([]) == "downloading"
    assert started == [["/usr/bin/ollama", "pull", "m:1"]]
    assert f.tick([]) == "downloading"    # still running: no second pull
    assert len(started) == 1


def test_fetcher_reports_ready_after_pull(monkeypatch):
    monkeypatch.setattr(node, "NODE_MODELS", ["m:1"])
    f = node.ModelFetcher()
    f.proc, f.model = FakeProc(code=0), "m:1"
    assert f.tick(["m:1"]) == "ready"


def test_heartbeat_advertises_only_ready_models():
    sent = {}

    class S:
        def post(self, url, json, timeout):
            sent.update(json)
            return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"status": "ok"})

    node.heartbeat(S(), "https://api", {"gpu_model": "x"}, [])
    assert sent["models"] == []
    node.heartbeat(S(), "https://api", {}, ["m:1"])
    assert sent["models"] == ["m:1"]


def test_no_jobs_are_claimed_until_a_model_is_ready(monkeypatch, tmp_path):
    creds = tmp_path / "credentials"
    creds.write_text("NODE_ID=node_1\nNODE_SECRET=s\n")
    monkeypatch.setattr(node, "CREDENTIALS_FILE", creds)
    monkeypatch.setattr(node, "read_credentials", lambda path=creds: {"NODE_ID": "node_1", "NODE_SECRET": "s"})
    monkeypatch.setattr(node, "get_gpu_info", lambda: {})
    monkeypatch.setattr(node, "installed_models", lambda: [])
    monkeypatch.setattr(node.ModelFetcher, "tick", lambda self, ready: "downloading")
    beats, claims = [], []
    monkeypatch.setattr(node, "heartbeat", lambda s, u, g=None, m=None: beats.append(m))
    monkeypatch.setattr(node, "claim_pending_job", lambda s, u: claims.append(1))
    calls = {"n": 0}

    def stop(_):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(node.time, "sleep", stop)
    with pytest.raises(KeyboardInterrupt):
        node.poll_for_jobs()
    assert beats and all(m == [] for m in beats)
    assert claims == []
