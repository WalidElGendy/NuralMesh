import random, pytest
from loops.shared.artifact_store import reputation_to_multiplier, get_provider_reputation

def test_rep_tiers():
    assert reputation_to_multiplier(0.96) == 1.20
    assert reputation_to_multiplier(0.95) == 1.20
    assert reputation_to_multiplier(0.91) == 1.10
    assert reputation_to_multiplier(0.90) == 1.10
    assert reputation_to_multiplier(0.85) == 1.00
    assert reputation_to_multiplier(0.80) == 1.00
    assert reputation_to_multiplier(0.75) == 0.90
    assert reputation_to_multiplier(0.70) == 0.90
    assert reputation_to_multiplier(0.65) == 0.80
    assert reputation_to_multiplier(0.00) == 0.80

def test_rep_boundaries():
    assert reputation_to_multiplier(1.00) == 1.20
    assert reputation_to_multiplier(0.699) == 0.80

def test_settle_has_qap():
    import app.stages.settle as m
    assert hasattr(m, "settle")
    assert callable(get_provider_reputation)
    assert callable(reputation_to_multiplier)

def test_qap_high_rep_bonus():
    base = 0.01
    assert base * reputation_to_multiplier(0.96) == pytest.approx(0.012)
    assert base * reputation_to_multiplier(0.65) == pytest.approx(0.008)

def test_qap_default_rep():
    rep = get_provider_reputation("unknown-xyz-9999")
    assert 0.50 <= rep <= 1.00
    assert reputation_to_multiplier(rep) in (0.80, 0.90, 1.00, 1.10, 1.20)

def test_judge_baseline_same():
    from loops.loop4_winrate_optimizer import judge_response
    for s in (0.1, 0.5, 0.9):
        assert judge_response("code", "claude-sonnet", s, rng=random.Random(1)) == "SAME"

def test_judge_high_score_better():
    from loops.loop4_winrate_optimizer import judge_response
    assert judge_response("math", "qwen-coder-7b", 0.90, rng=random.Random(42)) == "BETTER"

def test_judge_low_score_worse():
    from loops.loop4_winrate_optimizer import judge_response
    assert judge_response("reasoning", "llama-3.1-8b", 0.45, rng=random.Random(1)) == "WORSE"

def test_winrate_result():
    from loops.loop4_winrate_optimizer import WinRateResult
    r = WinRateResult(intent="code")
    assert r.win_rate == 0.0
    r.total_evaluated = 10; r.wins = 7; r.avg_cost_usd = 0.005
    assert r.win_rate == pytest.approx(0.70)
    d = r.to_dict()
    assert d["win_rate"] == pytest.approx(0.70, abs=0.001)

def test_composite_score():
    from loops.loop4_winrate_optimizer import WinRateResult, compute_composite_score
    results = {"code": WinRateResult(intent="code"), "math": WinRateResult(intent="math")}
    results["code"].total_evaluated = 60; results["code"].wins = 45
    results["math"].total_evaluated = 40; results["math"].wins = 20
    assert compute_composite_score(results) == pytest.approx(0.65)

def test_composite_empty():
    from loops.loop4_winrate_optimizer import compute_composite_score
    assert compute_composite_score({}) == 0.0

@pytest.mark.asyncio
async def test_loop4_run_skips_no_data():
    from loops.loop4_winrate_optimizer import run
    import fakeredis as fr
    outcome = await run(fr.FakeRedis())
    assert outcome["status"] == "skipped"

@pytest.mark.asyncio
async def test_loop4_evaluates_with_data(monkeypatch):
    from loops.loop4_winrate_optimizer import run
    from loops.shared.decisions_db import Decision, write_decision
    import fakeredis as fr

    # Prevent test from writing to real policy files
    import loops.loop4_winrate_optimizer as l4
    monkeypatch.setattr(l4, "save_policy", lambda name, data: None)

    r = fr.FakeRedis()
    for i in range(25):
        phash = "t" + str(i).zfill(4)
        write_decision(Decision(prompt_hash=phash, ladder_used="code", final_model="qwen-coder-7b", verifier_score=0.90, cost_usd=0.002), r)
    outcome = await run(r)
    assert outcome["status"] == "evaluated"
    assert "code" in outcome["intent_breakdown"]
