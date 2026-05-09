
import pytest
from app.lib.ratelimit import TIER_LIMITS, BETA_DAILY_LIMIT, DAY_SECONDS

class TestBetaTier:
    def test_beta_tier_exists_in_limits(self):
        assert "beta" in TIER_LIMITS

    def test_beta_per_minute_limit_is_30(self):
        assert TIER_LIMITS["beta"] == 30

    def test_beta_daily_limit_is_200(self):
        assert BETA_DAILY_LIMIT == 200

    def test_day_seconds_is_86400(self):
        assert DAY_SECONDS == 86400

    def test_beta_lower_than_pro(self):
        assert TIER_LIMITS["beta"] < TIER_LIMITS["pro"]

    def test_beta_higher_than_zero(self):
        assert TIER_LIMITS["beta"] > 0

    def test_all_expected_tiers_present(self):
        for tier in ("free", "beta", "pro", "admin"):
            assert tier in TIER_LIMITS, f"Missing tier: {tier}"

    def test_admin_is_highest(self):
        assert TIER_LIMITS["admin"] >= max(v for k, v in TIER_LIMITS.items() if k != "admin")
