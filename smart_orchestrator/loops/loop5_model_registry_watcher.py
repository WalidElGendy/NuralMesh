"""
Loop 5  Model Registry Watcher
Cron: daily

Responsibilities:
  1. Read app/policies/model_registry.json (list of known models with GA dates)
  2. Compare against models currently in ladders.json
  3. For each NEW model (in registry but not in any ladder):
       - Compute time_to_route = days since model went GA
       - Record in model_registry_history.json
  4. Suggest ladder insertions for new models (appended to matching intents)
  5. Write updated ladders.json if new models should be added
  6. Write model_registry_history.json with time_to_route per model

North-star metric owned: time-to-route improvement
  = days between a model going GA and the orchestrator picking it up.
  Loop 5 directly reduces this to near-zero by auto-discovering new models.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from loops.shared.artifact_store import get_ladders, load_policy, save_policy

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGISTRY_POLICY_NAME = "model_registry"
HISTORY_POLICY_NAME = "model_registry_history"

# Default intent mappings: when we see a model tag in the registry we try to
# place it onto the right ladder(s).  Keys are substring patterns; values are
# the ladder intents the model fits.
INTENT_TAGS: dict[str, list[str]] = {
    "coder":    ["code"],
    "code":     ["code"],
    "math":     ["math", "reasoning"],
    "reasoning":["reasoning"],
    "creative": ["creative"],
    "chat":     ["chat"],
    "instruct": ["chat", "factual"],
    "pro":      ["reasoning", "factual"],
    "flash":    ["factual", "chat"],
    "sonnet":   ["code", "creative", "reasoning"],
    "opus":     ["code", "creative", "reasoning", "math"],
    "gemini":   ["factual", "reasoning", "math"],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RegistryModel:
    """A model entry from model_registry.json."""
    model_id: str          # canonical short name, e.g. "gemma-3-27b"
    ga_date: str           # ISO-8601 date string "YYYY-MM-DD"
    provider: str          # "google", "anthropic", "meta", "ollama", 
    tags: list[str] = field(default_factory=list)  # hint words for placement
    description: str = ""


@dataclass
class RegistryWatchResult:
    """Result of one registry watcher run."""
    new_models: list[str] = field(default_factory=list)
    time_to_route_days: dict[str, int] = field(default_factory=dict)
    ladders_updated: bool = False
    ladders_touched: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _days_since(ga_date_str: str, today: date | None = None) -> int:
    """Return calendar days between ga_date and today (floor 0)."""
    try:
        ga = date.fromisoformat(ga_date_str)
    except ValueError:
        return 0
    ref = today or date.today()
    return max(0, (ref - ga).days)


def _infer_intents(model: RegistryModel) -> list[str]:
    """Infer which ladder intents this model belongs to from its tags + id."""
    intents: set[str] = set()
    search_text = (model.model_id + " " + " ".join(model.tags)).lower()
    for keyword, intent_list in INTENT_TAGS.items():
        if keyword in search_text:
            intents.update(intent_list)
    return sorted(intents) if intents else ["chat"]  # fallback to chat


def _load_registry() -> list[RegistryModel]:
    """Load model_registry.json  list[RegistryModel]."""
    raw: dict[str, Any] = load_policy(REGISTRY_POLICY_NAME)
    models_raw = raw.get("models", [])
    result = []
    for entry in models_raw:
        result.append(RegistryModel(
            model_id=entry.get("model_id", ""),
            ga_date=entry.get("ga_date", "2020-01-01"),
            provider=entry.get("provider", "unknown"),
            tags=entry.get("tags", []),
            description=entry.get("description", ""),
        ))
    return result


def _models_in_ladders(ladders: dict[str, list[str]]) -> set[str]:
    """Return the flat set of all model IDs currently in any ladder."""
    result: set[str] = set()
    for models in ladders.values():
        result.update(models)
    return result


def _insert_model_into_ladders(
    model: RegistryModel,
    ladders: dict[str, list[str]],
) -> list[str]:
    """
    Insert model into appropriate ladders.
    Returns list of touched intent names.
    New model is appended (lowest priority = tries it last in escalation).
    """
    intents = _infer_intents(model)
    touched = []
    for intent in intents:
        if intent in ladders and model.model_id not in ladders[intent]:
            ladders[intent].append(model.model_id)
            touched.append(intent)
    return touched


# ---------------------------------------------------------------------------
# Core run function (called by cron scheduler)
# ---------------------------------------------------------------------------

def run(today: date | None = None) -> RegistryWatchResult:
    """
    Main entry point for Loop 5.

    Steps:
      1. Load registry and current ladders
      2. Find models in registry not yet in ladders
      3. For each new model: compute time_to_route, insert into ladders
      4. Persist updated ladders.json and history
      5. Return RegistryWatchResult
    """
    result = RegistryWatchResult()

    registry = _load_registry()
    if not registry:
        return result  # nothing to do

    ladders = get_ladders()
    known_models = _models_in_ladders(ladders)

    # Load or create history
    history: dict[str, Any] = load_policy(HISTORY_POLICY_NAME)
    already_tracked: set[str] = set(history.get("models", {}).keys())

    for reg_model in registry:
        if reg_model.model_id in known_models:
            continue  # already in a ladder
        if reg_model.model_id in already_tracked:
            continue  # seen before but still not in ladders (manual decision)

        # New model detected
        days = _days_since(reg_model.ga_date, today)
        result.new_models.append(reg_model.model_id)
        result.time_to_route_days[reg_model.model_id] = days

        # Insert into ladders
        touched = _insert_model_into_ladders(reg_model, ladders)
        result.ladders_touched.extend(touched)

    if result.new_models:
        result.ladders_updated = True

        # Persist updated ladders (keep the {"ladders": ...} wrapper)
        save_policy("ladders", {"ladders": ladders})

        # Update history
        models_history = history.get("models", {})
        now_iso = datetime.now(timezone.utc).isoformat()
        for model_id in result.new_models:
            models_history[model_id] = {
                "detected_at": now_iso,
                "time_to_route_days": result.time_to_route_days[model_id],
            }
        history["models"] = models_history
        save_policy(HISTORY_POLICY_NAME, history)

    return result
