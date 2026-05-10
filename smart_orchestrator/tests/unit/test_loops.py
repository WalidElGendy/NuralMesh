"""Tests for Self-Improvement Layer: loops/shared + loop2 + loop3."""
import json
import os
import time
import pytest
import fakeredis

from loops.shared.decisions_db import (
    Decision, write_decision, query_decisions, hash_prompt, STREAM_KEY
)
from loops.shared.ab_gate import ABGate, ArtifactMetrics
from loops.shared.artifact_store import (
    load_policy, save_policy, get_ladders, get_provider_reputation,
    update_provider_reputation
)
from loops.loop2_cache_curator import run_cache_curator, _freshness_score
from loops.loop3_provider_scorer import run_provider_scorer, _compute_provider_score


#  decisions_db 

def test_decision_write_and_read():
    redis = fakeredis.FakeRedis()
    d = Decision(prompt_hash="abc123", final_model="llama-3.1-8b",
                 ladder_used="chat", latency_ms=120, cost_usd=0.0001)
    write_decision(d, redis)
    results = query_decisions(redis)
    assert len(results) == 1
    assert results[0].final_model == "llama-3.1-8b"
    assert results[0].latency_ms == 120


def test_decision_filter_by_feedback():
    redis = fakeredis.FakeRedis()
    d1 = Decision(prompt_hash="h1", user_feedback="thumbs_up")
    d2 = Decision(prompt_hash="h2", user_feedback="thumbs_down")
    write_decision(d1, redis)
    write_decision(d2, redis)
    ups = query_decisions(redis, filter_feedback="thumbs_up")
    assert len(ups) == 1
    assert ups[0].prompt_hash == "h1"


def test_hash_prompt_never_returns_raw():
    raw = "What is 2+2?"
    h = hash_prompt(raw)
    assert raw not in h
    assert len(h) == 16


def test_decision_round_trip_with_lists():
    redis = fakeredis.FakeRedis()
    d = Decision(
        prompt_hash="xyz",
        rungs_attempted=["llama-3.1-8b", "deepseek-v3"],
        providers_paid=[{"node_id": "n1", "amount": 0.01}],
        cache_hit=True,
    )
    write_decision(d, redis)
    results = query_decisions(redis)
    assert results[0].cache_hit is True
    assert isinstance(results[0].rungs_attempted, list)
    assert results[0].rungs_attempted == ["llama-3.1-8b", "deepseek-v3"]


#  ab_gate 

def test_ab_gate_promotes_improvement():
    gate = ABGate()
    old = ArtifactMetrics(cost_per_1k=0.10, win_rate=0.60, cache_hit_rate=0.50, classifier_accuracy=0.80)
    new = ArtifactMetrics(cost_per_1k=0.09, win_rate=0.65, cache_hit_rate=0.55, classifier_accuracy=0.82)
    ok, reason = gate.should_promote(old, new)
    assert ok, reason


def test_ab_gate_blocks_cost_regression():
    gate = ABGate()
    old = ArtifactMetrics(cost_per_1k=0.10, win_rate=0.60)
    new = ArtifactMetrics(cost_per_1k=0.20, win_rate=0.70)
    ok, reason = gate.should_promote(old, new)
    assert not ok
    assert "cost" in reason


def test_ab_gate_blocks_winrate_regression():
    gate = ABGate()
    old = ArtifactMetrics(cost_per_1k=0.10, win_rate=0.80)
    new = ArtifactMetrics(cost_per_1k=0.08, win_rate=0.70)
    ok, reason = gate.should_promote(old, new)
    assert not ok
    assert "win-rate" in reason


def test_ab_gate_evaluate_dict_interface():
    gate = ABGate()
    ok, _ = gate.evaluate(
        {"cost_per_1k": 0.0, "win_rate": 0.5},
        {"cost_per_1k": 0.0, "win_rate": 0.8, "cache_hit_rate": 0.3},
    )
    assert ok


#  artifact_store 

def test_artifact_store_load_ladders():
    ladders = get_ladders()
    assert "chat" in ladders
    assert "code" in ladders
    assert "llama-3.1-8b" in ladders["chat"]


def test_artifact_store_provider_reputation_default():
    rep = get_provider_reputation("unknown-provider-xyz")
    assert 0.5 <= rep <= 1.0


#  loop2 cache curator 

def test_freshness_score_formula():
    score = _freshness_score(verifier_score=0.9, hit_count=10, days_old=1.0)
    assert score == pytest.approx(min(1.0, 0.9 * 10 / 1.0))


@pytest.mark.asyncio
async def test_run_cache_curator_empty():
    redis = fakeredis.FakeRedis()
    result = await run_cache_curator(redis, now=time.time())
    assert result["evicted"] == 0
    assert result["decisions_examined"] == 0


#  loop3 provider scorer 

def test_compute_provider_score_ewma():
    score = _compute_provider_score(
        verifier_scores=[0.9, 0.85, 0.92],
        refusal_count=0,
        total_count=3,
        current_reputation=0.80,
    )
    assert 0.80 <= score <= 1.00


@pytest.mark.asyncio
async def test_run_provider_scorer_empty():
    redis = fakeredis.FakeRedis()
    result = await run_provider_scorer(redis, now=time.time())
    assert result["decisions_examined"] == 0
    assert isinstance(result["providers_scored"], int)
