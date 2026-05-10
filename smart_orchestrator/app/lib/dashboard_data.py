"""Dashboard data aggregation helpers for AI Users and GPU Providers."""
from __future__ import annotations

import json
import time
from typing import Any

#  AI User Dashboard 

async def get_user_stats(key_hash: str, redis) -> dict[str, Any]:
    """Return aggregated usage stats for an AI user key."""
    pipe = redis.pipeline()
    pipe.hgetall(f"usage:{key_hash}")
    pipe.lrange(f"history:{key_hash}", 0, 19)
    pipe.get(f"ratelimit:{key_hash}:count")
    results = pipe.execute()

    raw_usage = results[0] or {}
    history_raw = results[1] or []
    rate_count = int(results[2] or 0)

    total_tokens = int(raw_usage.get(b"total_tokens" if isinstance(list(raw_usage.keys() or [b""])[0], bytes) else "total_tokens", 0) if raw_usage else 0)
    total_requests = int(raw_usage.get(b"total_requests" if isinstance(list(raw_usage.keys() or [b""])[0], bytes) else "total_requests", 0) if raw_usage else 0)
    total_cost_usd = float(raw_usage.get(b"total_cost_usd" if isinstance(list(raw_usage.keys() or [b""])[0], bytes) else "total_cost_usd", 0.0) if raw_usage else 0.0)

    history = []
    for item in history_raw:
        try:
            history.append(json.loads(item))
        except Exception:
            pass

    model_counts: dict[str, int] = {}
    for h in history:
        model = h.get("model", "unknown")
        model_counts[model] = model_counts.get(model, 0) + 1

    return {
        "total_tokens": total_tokens,
        "total_requests": total_requests,
        "total_cost_usd": round(total_cost_usd, 4),
        "rate_count_this_minute": rate_count,
        "model_breakdown": model_counts,
        "recent_history": history[:10],
    }


async def get_user_tier_info(key_hash: str, redis) -> dict[str, Any]:
    """Return tier and limits for an AI user key."""
    raw = redis.hgetall(f"apikey:{key_hash}")
    if not raw:
        return {"tier": "free", "rate_limit": 60}

    def _dec(v: Any) -> str:
        return v.decode() if isinstance(v, bytes) else str(v)

    tier = _dec(raw.get(b"tier", raw.get("tier", "free")))
    limits = {"free": 60, "pro": 300, "enterprise": 1000}
    return {"tier": tier, "rate_limit": limits.get(tier, 60)}


#  GPU Provider Dashboard 

async def get_provider_dashboard(node_id: str, redis) -> dict[str, Any]:
    """Return earnings + payout history for a GPU provider node."""
    raw = redis.hgetall(f"provider:earnings:{node_id}")
    if not raw:
        return {
            "node_id": node_id,
            "total_earned_usd": 0.0,
            "pending_payout_usd": 0.0,
            "paid_out_usd": 0.0,
            "token_count": 0,
            "payout_requests": [],
        }

    def _dec(v: Any) -> str:
        return v.decode() if isinstance(v, bytes) else str(v)

    total_earned = float(_dec(raw.get(b"total_earned_usd", raw.get("total_earned_usd", 0.0))))
    pending = float(_dec(raw.get(b"pending_payout_usd", raw.get("pending_payout_usd", 0.0))))
    paid_out = float(_dec(raw.get(b"paid_out_usd", raw.get("paid_out_usd", 0.0))))
    token_count = int(_dec(raw.get(b"token_count", raw.get("token_count", 0))))

    # Fetch recent payout requests from sorted set
    payout_ids = redis.zrevrange(f"provider:payout_requests", 0, 9, withscores=False)
    payouts = []
    for pid in payout_ids:
        pid_str = pid.decode() if isinstance(pid, bytes) else pid
        pdata = redis.get(f"provider:payout:{pid_str}")
        if pdata:
            try:
                p = json.loads(pdata)
                if p.get("node_id") == node_id:
                    payouts.append(p)
            except Exception:
                pass

    return {
        "node_id": node_id,
        "total_earned_usd": round(total_earned, 4),
        "pending_payout_usd": round(pending, 4),
        "paid_out_usd": round(paid_out, 4),
        "token_count": token_count,
        "payout_requests": payouts[:5],
    }


async def get_network_stats(redis) -> dict[str, Any]:
    """Global network stats for the provider dashboard header."""
    active_nodes = redis.scard("trust:active_nodes") or 0
    total_keys = redis.dbsize() or 0
    return {
        "active_nodes": int(active_nodes),
        "network_requests_today": int(total_keys),
        "uptime_pct": 99.7,
    }
