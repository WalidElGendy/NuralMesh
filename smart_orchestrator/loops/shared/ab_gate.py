"""A/B gate  promotes new artifact only if it beats the old one on key metrics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ArtifactMetrics:
    """Metrics snapshot for a policy artifact version."""
    cost_per_1k: float = 0.0        # USD per 1000 queries (lower is better)
    win_rate: float = 0.0           # LLM-as-judge win rate vs. always-Sonnet (higher is better)
    cache_hit_rate: float = 0.0     # Quality-weighted cache hit rate (higher is better)
    classifier_accuracy: float = 0.0  # Eval set accuracy (higher is better)

    def score(self) -> float:
        """Composite score: higher is better. Cost is inverted."""
        cost_score = max(0.0, 1.0 - self.cost_per_1k)
        return (cost_score + self.win_rate + self.cache_hit_rate + self.classifier_accuracy) / 4.0


class ABGate:
    """
    Compares new artifact metrics against old and decides whether to promote.

    Promotion criteria (must pass ALL):
    - new.cost_per_1k <= old.cost_per_1k * 1.05  (allow up to 5% cost regression)
    - new.win_rate >= old.win_rate - 0.02          (allow up to 2pp win-rate regression)
    - new.score() > old.score()                    (composite must improve)
    """

    def __init__(self, min_improvement: float = 0.001):
        self.min_improvement = min_improvement

    def should_promote(self, old: ArtifactMetrics, new: ArtifactMetrics) -> tuple[bool, str]:
        """
        Returns (should_promote, reason).
        """
        cost_ok = new.cost_per_1k <= old.cost_per_1k * 1.05 or old.cost_per_1k == 0.0
        win_ok = new.win_rate >= old.win_rate - 0.02 or old.win_rate == 0.0
        score_ok = (new.score() - old.score()) >= self.min_improvement

        if not cost_ok:
            return False, f"cost regression: {new.cost_per_1k:.4f} > {old.cost_per_1k * 1.05:.4f}"
        if not win_ok:
            return False, f"win-rate regression: {new.win_rate:.3f} < {old.win_rate - 0.02:.3f}"
        if not score_ok:
            return False, f"composite score did not improve: {new.score():.4f} vs {old.score():.4f}"

        return True, f"promoted: score {old.score():.4f} -> {new.score():.4f}"

    def evaluate(self, old_metrics: dict[str, Any], new_metrics: dict[str, Any]) -> tuple[bool, str]:
        """Convenience: accept plain dicts."""
        old = ArtifactMetrics(**{k: v for k, v in old_metrics.items() if k in ArtifactMetrics.__dataclass_fields__})
        new = ArtifactMetrics(**{k: v for k, v in new_metrics.items() if k in ArtifactMetrics.__dataclass_fields__})
        return self.should_promote(old, new)
