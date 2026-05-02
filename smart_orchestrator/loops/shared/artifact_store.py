"""Versioned policy artifact store  reads/writes app/policies/*.json."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

POLICIES_DIR = Path(__file__).resolve().parents[2] / "app" / "policies"


def load_policy(name: str) -> dict[str, Any]:
    """Load a policy JSON file by name (without .json extension)."""
    path = POLICIES_DIR / f"{name}.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_policy(name: str, data: dict[str, Any]) -> Path:
    """Save a policy dict to app/policies/<name>.json, bump version timestamp."""
    POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = POLICIES_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def get_ladders() -> dict[str, list[str]]:
    """Return the current ladder config."""
    policy = load_policy("ladders")
    return policy.get("ladders", {})


def get_routing_policy() -> dict[str, Any]:
    """Return the current routing policy."""
    return load_policy("routing_policy")


def get_provider_reputation(provider_id: str) -> float:
    """Return EWMA reputation score for a provider, default 0.80."""
    policy = load_policy("provider_reputation")
    providers = policy.get("providers", {})
    return providers.get(provider_id, {}).get("reputation", policy.get("default_reputation", 0.80))


def update_provider_reputation(provider_id: str, new_score: float) -> None:
    """Update a single provider's reputation in the JSON store."""
    policy = load_policy("provider_reputation")
    if "providers" not in policy:
        policy["providers"] = {}
    policy["providers"][provider_id] = {"reputation": round(new_score, 4)}
    save_policy("provider_reputation", policy)


def reputation_to_multiplier(reputation: float) -> float:
    """Convert provider reputation score to rate multiplier.

    Rate multipliers (per spec):
        rep >= 0.95  ->  1.20x
        rep >= 0.90  ->  1.10x
        rep >= 0.80  ->  1.00x  (baseline)
        rep >= 0.70  ->  0.90x
        else         ->  0.80x
    """
    if reputation >= 0.95:
        return 1.20
    if reputation >= 0.90:
        return 1.10
    if reputation >= 0.80:
        return 1.00
    if reputation >= 0.70:
        return 0.90
    return 0.80
