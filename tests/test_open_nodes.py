"""Open (community) nodes only ever get public work."""
from datetime import UTC, datetime

import mesh_router


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def __getattr__(self, name):           # select / eq / limit / in_ … chain
        return lambda *a, **k: self

    def execute(self):
        return _Res(self.rows)


class _SB:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        return _Q(self.rows if name == "providers" else [])


def _node(node_id, trust):
    return {"node_id": node_id, "status": "online", "models": ["llama3.3:70b-instruct-q4_K_M"],
            "last_seen_at": datetime.now(UTC).isoformat(), "max_concurrent": 1, "accepts": True,
            "cooldown_until": None, "trust": trust}


def test_private_turns_never_reach_open_nodes():
    sb = _SB([_node("open1", "open")])
    nodes, why = mesh_router._eligible_nodes(sb, "llama3.3:70b-instruct-q4_K_M", "private")
    assert nodes == [] and why == "no_trusted_nodes"


def test_public_turns_may_use_open_nodes():
    sb = _SB([_node("open1", "open")])
    nodes, why = mesh_router._eligible_nodes(sb, "llama3.3:70b-instruct-q4_K_M", "public")
    assert why is None and [n["node_id"] for n in nodes] == ["open1"]


def test_trusted_nodes_serve_private_turns():
    sb = _SB([_node("open1", "open"), _node("vetted", "trusted")])
    nodes, why = mesh_router._eligible_nodes(sb, "llama3.3:70b-instruct-q4_K_M", "private")
    assert why is None and [n["node_id"] for n in nodes] == ["vetted"]
