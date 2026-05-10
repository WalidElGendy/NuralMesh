# ADR 0010  Beta Rate Limit Tier

**Status:** Accepted  
**Date:** 2025-05-03

## Context
During beta, we want generous but not unlimited access to avoid abuse and cost overruns.

## Decision
Add a `beta` tier as the **default for all new users** during beta period:
- 10 requests/minute (per-key sliding window, same as `free`)
- 100 requests/day (separate daily counter)
- No concurrent request cap

This is configured in `app/lib/ratelimit.py` as:
```python
TIER_LIMITS = {"beta": 10, ...}
BETA_DAILY_LIMIT = 100
```

When assigning API keys via `/admin/keys`, set `tier=beta` during the beta period.

## Consequences
+ New users get a usable quota without us accidentally giving unlimited access
+ Easy to upgrade individual users to `pro` when beta ends
+ Existing `free`/`pro`/`admin` tiers unchanged
- Need to manually re-tier users from `beta` to `pro` when soft launch ends
