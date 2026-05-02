
import pytest
from datetime import date
from unittest.mock import patch

from loops.loop5_model_registry_watcher import (
    _days_since,
    _infer_intents,
    _models_in_ladders,
    _insert_model_into_ladders,
    _load_registry,
    run,
    RegistryModel,
    RegistryWatchResult,
)


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestDaysSince:
    def test_zero_when_ga_today(self):
        today = date(2025, 5, 2)
        assert _days_since("2025-05-02", today=today) == 0

    def test_positive_days(self):
        today = date(2025, 5, 2)
        assert _days_since("2025-04-02", today=today) == 30

    def test_floor_at_zero_for_future(self):
        today = date(2025, 5, 2)
        assert _days_since("2026-01-01", today=today) == 0

    def test_invalid_date_returns_zero(self):
        assert _days_since("not-a-date") == 0

    def test_uses_real_today_when_none(self):
        result = _days_since("2020-01-01")
        assert result > 0  # far past date


class TestInferIntents:
    def test_coder_tag_gives_code(self):
        m = RegistryModel("my-coder-7b", "2025-01-01", "qwen", tags=["coder"])
        intents = _infer_intents(m)
        assert "code" in intents

    def test_math_tag_gives_math_and_reasoning(self):
        m = RegistryModel("math-model", "2025-01-01", "x", tags=["math"])
        intents = _infer_intents(m)
        assert "math" in intents
        assert "reasoning" in intents

    def test_gemini_in_model_id(self):
        m = RegistryModel("gemini-flash-2", "2025-01-01", "google", tags=[])
        intents = _infer_intents(m)
        assert "factual" in intents

    def test_no_matching_tags_falls_back_to_chat(self):
        m = RegistryModel("unknown-model-x", "2025-01-01", "unk", tags=[])
        intents = _infer_intents(m)
        assert intents == ["chat"]

    def test_sonnet_in_id_gives_code_creative_reasoning(self):
        m = RegistryModel("claude-sonnet-4", "2025-01-01", "anthropic", tags=[])
        intents = _infer_intents(m)
        assert "code" in intents
        assert "creative" in intents
        assert "reasoning" in intents


class TestModelsInLadders:
    def test_flat_set_extracted(self):
        ladders = {
            "code": ["model-a", "model-b"],
            "chat": ["model-c"],
        }
        result = _models_in_ladders(ladders)
        assert result == {"model-a", "model-b", "model-c"}

    def test_empty_ladders(self):
        assert _models_in_ladders({}) == set()


class TestInsertModelIntoLadders:
    def test_inserts_into_matching_intents(self):
        ladders = {"code": ["existing-model"], "chat": ["other-model"]}
        m = RegistryModel("new-coder", "2025-01-01", "x", tags=["coder"])
        touched = _insert_model_into_ladders(m, ladders)
        assert "code" in touched
        assert "new-coder" in ladders["code"]

    def test_no_duplicate_insertion(self):
        ladders = {"code": ["existing-model"]}
        m = RegistryModel("existing-model", "2025-01-01", "x", tags=["coder"])
        touched = _insert_model_into_ladders(m, ladders)
        assert touched == []
        assert ladders["code"].count("existing-model") == 1

    def test_inserts_into_multiple_intents(self):
        ladders = {"reasoning": ["m1"], "math": ["m2"], "code": ["m3"]}
        m = RegistryModel("deepseek-r2", "2025-01-01", "deepseek", tags=["reasoning", "math", "code"])
        touched = _insert_model_into_ladders(m, ladders)
        assert len(touched) >= 2  # at least reasoning and math

    def test_intent_not_in_ladders_skipped(self):
        ladders = {"code": []}  # no "creative" ladder
        m = RegistryModel("creative-gpt", "2025-01-01", "x", tags=["creative"])
        touched = _insert_model_into_ladders(m, ladders)
        assert "creative" not in touched


# ---------------------------------------------------------------------------
# Integration-style tests for run()
# ---------------------------------------------------------------------------

SAMPLE_LADDERS = {
    "code":      ["qwen-coder-7b", "deepseek-v3", "claude-sonnet"],
    "creative":  ["llama-3.1-8b", "claude-sonnet"],
    "factual":   ["llama-3.1-8b", "gemini-2.5-pro"],
    "reasoning": ["llama-3.1-8b", "deepseek-v3", "claude-sonnet"],
    "math":      ["qwen-coder-7b", "deepseek-v3", "gemini-2.5-pro"],
    "chat":      ["llama-3.1-8b"],
}

SAMPLE_REGISTRY = [
    RegistryModel("llama-3.1-8b",   "2024-07-23", "meta",      tags=["instruct", "chat"]),
    RegistryModel("claude-sonnet",  "2024-10-22", "anthropic", tags=["sonnet"]),
    RegistryModel("gemma-3-27b",    "2025-03-12", "google",    tags=["instruct", "chat", "reasoning"]),
    RegistryModel("llama-3.3-70b",  "2024-12-06", "meta",      tags=["instruct", "reasoning", "math"]),
]


class TestRun:
    def test_skips_models_already_in_ladders(self, monkeypatch, tmp_path):
        """Models already in ladders should not appear in new_models."""
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher._load_registry",
            lambda: [RegistryModel("llama-3.1-8b", "2024-07-23", "meta", tags=["chat"])]
        )
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.get_ladders",
            lambda: {"chat": ["llama-3.1-8b"]}
        )
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.load_policy",
            lambda name: {}
        )
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.save_policy",
            lambda name, data: None
        )
        result = run(today=date(2025, 5, 2))
        assert result.new_models == []
        assert result.ladders_updated is False

    def test_detects_new_model(self, monkeypatch):
        """A model in registry but not in ladders should be detected."""
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher._load_registry",
            lambda: [RegistryModel("gemma-3-27b", "2025-03-12", "google", tags=["reasoning"])]
        )
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.get_ladders",
            lambda: {"reasoning": ["llama-3.1-8b"]}
        )
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.load_policy",
            lambda name: {}
        )
        saved = {}
        def fake_save(name, data):
            saved[name] = data
        monkeypatch.setattr("loops.loop5_model_registry_watcher.save_policy", fake_save)

        result = run(today=date(2025, 5, 2))
        assert "gemma-3-27b" in result.new_models
        assert result.ladders_updated is True
        assert "gemma-3-27b" in result.time_to_route_days

    def test_time_to_route_calculation(self, monkeypatch):
        """time_to_route_days should equal days between ga_date and run date."""
        today = date(2025, 5, 2)
        ga_date = "2025-04-02"  # exactly 30 days ago
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher._load_registry",
            lambda: [RegistryModel("new-model-x", ga_date, "x", tags=["chat"])]
        )
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.get_ladders",
            lambda: {"chat": []}
        )
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.load_policy",
            lambda name: {}
        )
        monkeypatch.setattr("loops.loop5_model_registry_watcher.save_policy", lambda n, d: None)

        result = run(today=today)
        assert result.time_to_route_days["new-model-x"] == 30

    def test_skips_already_tracked_model(self, monkeypatch):
        """Models in history but not in ladders should not be re-inserted."""
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher._load_registry",
            lambda: [RegistryModel("tracked-model", "2025-01-01", "x", tags=["chat"])]
        )
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.get_ladders",
            lambda: {"chat": []}  # not in ladders
        )
        # But it IS in history
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.load_policy",
            lambda name: {"models": {"tracked-model": {"detected_at": "...", "time_to_route_days": 5}}}
        )
        monkeypatch.setattr("loops.loop5_model_registry_watcher.save_policy", lambda n, d: None)

        result = run(today=date(2025, 5, 2))
        assert result.new_models == []

    def test_empty_registry_returns_empty_result(self, monkeypatch):
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher._load_registry",
            lambda: []
        )
        result = run()
        assert result.new_models == []
        assert result.ladders_updated is False

    def test_ladders_updated_when_new_model_inserted(self, monkeypatch):
        """When new models found, ladders.json must be persisted."""
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher._load_registry",
            lambda: [RegistryModel("qwen3-32b", "2025-04-28", "qwen", tags=["reasoning", "math", "coder"])]
        )
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.get_ladders",
            lambda: {"code": [], "math": [], "reasoning": []}
        )
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.load_policy",
            lambda name: {}
        )
        saved = {}
        monkeypatch.setattr("loops.loop5_model_registry_watcher.save_policy", lambda n, d: saved.update({n: d}))

        result = run(today=date(2025, 5, 2))
        assert result.ladders_updated is True
        assert "ladders" in saved
        assert "ladders" in saved["ladders"]  # wrapped format
        # qwen3-32b should appear in at least one ladder
        flat = set()
        for v in saved["ladders"]["ladders"].values():
            flat.update(v)
        assert "qwen3-32b" in flat

    def test_history_written_for_new_model(self, monkeypatch):
        """History policy should be saved with new model entry."""
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher._load_registry",
            lambda: [RegistryModel("new-flash-model", "2025-04-01", "google", tags=["flash", "factual"])]
        )
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.get_ladders",
            lambda: {"factual": [], "chat": []}
        )
        monkeypatch.setattr(
            "loops.loop5_model_registry_watcher.load_policy",
            lambda name: {}
        )
        saved = {}
        monkeypatch.setattr("loops.loop5_model_registry_watcher.save_policy", lambda n, d: saved.update({n: d}))

        run(today=date(2025, 5, 2))
        assert "model_registry_history" in saved
        hist = saved["model_registry_history"]
        assert "models" in hist
        assert "new-flash-model" in hist["models"]
        entry = hist["models"]["new-flash-model"]
        assert "time_to_route_days" in entry
        assert "detected_at" in entry


# ---------------------------------------------------------------------------
# RegistryWatchResult properties
# ---------------------------------------------------------------------------

class TestRegistryWatchResult:
    def test_default_result_is_empty(self):
        r = RegistryWatchResult()
        assert r.new_models == []
        assert r.time_to_route_days == {}
        assert r.ladders_updated is False
        assert r.ladders_touched == []

    def test_populated_result(self):
        r = RegistryWatchResult(
            new_models=["model-a"],
            time_to_route_days={"model-a": 15},
            ladders_updated=True,
            ladders_touched=["code"],
        )
        assert r.new_models == ["model-a"]
        assert r.time_to_route_days["model-a"] == 15
        assert r.ladders_updated is True
