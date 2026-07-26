"""Sovereign routing — decide whether a turn is served by the mesh or bought.

THE POLICY
Every token a MeshNet provider serves is a token not bought from an outside
LLM. So the router's job is: send work to the mesh whenever the mesh can
actually take it, buy the remainder, and record *why* each purchase happened.

    mesh available?  -> dispatch to a node, provider earns credits
    mesh not able?   -> fallback, platform pays cash, reason recorded

There is no fixed 70/30 split, and deliberately so. A fixed split would keep
buying tokens after the mesh could have served them, and would overload the
mesh before it was ready. The share is an *outcome* of capacity, so it rises
on its own as providers join — no config change, no redeploy. NM_MESH_MAX_SHARE
exists only to cap the mesh during early testing, not to floor it.

FAIL FAST, NOT SLOW
The mesh is offered the job first, but only for `dispatch_deadline` seconds. If
no node claims it in that window the job is abandoned and the turn falls back —
before the user has seen a single token. A thin mesh therefore costs money, not
user experience.

THE REASON CODES ARE THE ROADMAP
Every fallback records one of:

    no_nodes           nobody is online          -> recruit providers
    no_capacity        online but all busy       -> recruit, or raise max_concurrent
    unhealthy          online but failing        -> support the providers you have
    model_unavailable  nobody serves this model  -> pin the model in onboarding
    unclaimed          online but too slow to    -> tune node poll interval
                       pick the job up
    share_cap          throttled by config       -> raise NM_MESH_MAX_SHARE

`select * from fallback_reasons_7d` orders that list by what it is costing.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

# The model the mesh is being built to serve.
MESH_MODEL = os.environ.get("NM_MESH_MODEL", "llama3.3:70b-instruct-q4_K_M")

# What we buy while the mesh is thin.
FALLBACK_MODEL = os.environ.get("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3.1")
FALLBACK_LABEL = os.environ.get("NM_PROVIDER_LABEL", "siliconflow")

# Ceiling on mesh share, for canarying. 1.0 = use the mesh whenever it can
# take the work, which is the intended steady state.
MESH_MAX_SHARE = float(os.environ.get("NM_MESH_MAX_SHARE", "1.0"))

# How long a turn may wait for a node to pick it up before we give up and buy.
DISPATCH_DEADLINE_S = float(os.environ.get("NM_DISPATCH_DEADLINE_S", "4"))

# How long a claimed job may go silent before its lease is reaped.
LEASE_S = int(os.environ.get("NM_LEASE_SECONDS", "120"))

# Health gates a node must pass to receive traffic.
MIN_SUCCESS_RATE = float(os.environ.get("NM_MIN_SUCCESS_RATE", "0.90"))
MAX_P95_MS = int(os.environ.get("NM_MAX_P95_MS", "15000"))
HEARTBEAT_STALE_S = int(os.environ.get("NM_HEARTBEAT_STALE_S", "90"))

# Economics, USD per million tokens.
FALLBACK_USD_PER_MTOK = float(os.environ.get("NM_FALLBACK_USD_PER_MTOK", "0.90"))
MESH_CREDIT_PER_MTOK = float(os.environ.get("NM_MESH_CREDIT_PER_MTOK", "0.89"))

MESH_ENABLED = os.environ.get("NM_MESH_ENABLED", "1").strip() != "0"


class MeshUnavailable(Exception):
    """Raised when the mesh could not serve a turn. Carries the reason code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass
class Decision:
    target: str                       # 'mesh' | 'fallback'
    reason: str | None = None         # why not mesh
    model: str = FALLBACK_MODEL
    candidates: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------
# capacity
# --------------------------------------------------------------------------

def _eligible_nodes(supabase, model: str) -> tuple[list[dict], str | None]:
    """Nodes that could serve `model` right now, and why not if none can."""
    try:
        res = (
            supabase.table("providers")
            .select("node_id,status,models,success_rate,latency_p50_ms,latency_p95_ms,"
                    "last_seen_at,max_concurrent,cooldown_until,accepts")
            .eq("status", "online")
            .limit(200)
            .execute()
        )
        rows = res.data or []
    except Exception:
        logger.warning("router_provider_query_failed", exc_info=True)
        return [], "no_nodes"

    if not rows:
        return [], "no_nodes"

    now = time.time()

    def fresh(r):
        ts = r.get("last_seen_at")
        if not ts:
            return False
        try:
            from datetime import datetime
            seen = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
            return now - seen < HEARTBEAT_STALE_S
        except Exception:
            return False

    live = [r for r in rows if fresh(r) and r.get("accepts", True)]
    if not live:
        return [], "unhealthy"

    cooling = [r for r in live if r.get("cooldown_until")]
    live = [r for r in live if not r.get("cooldown_until")]
    if not live:
        return [], "unhealthy"

    serves = [r for r in live if _serves(r.get("models"), model)]
    if not serves:
        return [], "model_unavailable"

    healthy = [
        r for r in serves
        if (r.get("success_rate") is None or float(r["success_rate"]) >= MIN_SUCCESS_RATE)
        and (r.get("latency_p95_ms") is None or int(r["latency_p95_ms"]) <= MAX_P95_MS)
    ]
    if not healthy:
        return [], "unhealthy"

    return healthy, None


def _serves(models: Any, model: str) -> bool:
    if not models:
        return False
    if isinstance(models, str):
        try:
            models = json.loads(models)
        except Exception:
            models = [models]
    names = [str(m) for m in (models if isinstance(models, list) else [models])]
    # Match on the family, so llama3.3:70b-instruct-q4_K_M and
    # llama3.3:70b-instruct-q5_K_M both count as serving the 70B.
    fam = model.split(":")[0].lower()
    return any(n.lower() == model.lower() or n.split(":")[0].lower() == fam for n in names)


def _free_capacity(supabase, nodes: list[dict]) -> int:
    """Total free slots across the eligible nodes."""
    ids = [n["node_id"] for n in nodes if n.get("node_id")]
    if not ids:
        return 0
    try:
        res = (
            supabase.table("jobs")
            .select("node_id")
            .in_("status", ["claimed", "streaming"])
            .in_("node_id", ids)
            .limit(1000)
            .execute()
        )
        busy: dict[str, int] = {}
        for row in res.data or []:
            busy[row["node_id"]] = busy.get(row["node_id"], 0) + 1
    except Exception:
        logger.warning("router_capacity_query_failed", exc_info=True)
        busy = {}

    return sum(
        max(0, int(n.get("max_concurrent") or 1) - busy.get(n["node_id"], 0))
        for n in nodes
    )


def _recent_mesh_share(supabase, window_minutes: int = 60) -> float:
    """Mesh share over the recent window, used only to honour MESH_MAX_SHARE."""
    if MESH_MAX_SHARE >= 1.0:
        return 0.0
    try:
        from datetime import UTC, datetime, timedelta
        since = (datetime.now(UTC) - timedelta(minutes=window_minutes)).isoformat()
        res = (
            supabase.table("routing_events")
            .select("target")
            .gte("created_at", since)
            .limit(2000)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return 0.0
        return sum(1 for r in rows if r["target"] == "mesh") / len(rows)
    except Exception:
        return 0.0


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------

def decide(supabase, model: str | None = None) -> Decision:
    """Should this turn go to the mesh?"""
    model = model or MESH_MODEL

    if not MESH_ENABLED:
        return Decision("fallback", "disabled")

    nodes, why = _eligible_nodes(supabase, model)
    if why:
        return Decision("fallback", why)

    if _free_capacity(supabase, nodes) <= 0:
        return Decision("fallback", "no_capacity")

    if MESH_MAX_SHARE < 1.0 and _recent_mesh_share(supabase) >= MESH_MAX_SHARE:
        return Decision("fallback", "share_cap")

    return Decision("mesh", None, model=model, candidates=nodes)


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

def enqueue(supabase, *, messages, model, params, user_id, conversation_id) -> str:
    from datetime import UTC, datetime, timedelta
    job_id = str(uuid.uuid4())
    deadline = (datetime.now(UTC) + timedelta(seconds=DISPATCH_DEADLINE_S)).isoformat()
    supabase.table("jobs").insert({
        "id": job_id,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "model": model,
        "messages": messages,
        "params": params,
        "dispatch_deadline": deadline,
    }).execute()
    return job_id


def stream_job(supabase, job_id: str) -> Iterator[tuple[str, str, dict]]:
    """Relay a mesh job's output.

    Yields ("delta", chunk, {}) as the node posts chunks, then
    ("done", full_text, meta). Raises MeshUnavailable if no node claims the job
    inside its dispatch window — the caller then falls back, and because no
    token has been emitted yet, the user sees nothing but a slightly slower
    first token.
    """
    t0 = time.perf_counter()
    seq = 0
    parts: list[str] = []
    claimed = False
    ttft_ms: int | None = None

    poll_s = 0.15
    deadline = t0 + DISPATCH_DEADLINE_S
    hard_deadline = t0 + LEASE_S

    while True:
        now = time.perf_counter()

        if not claimed:
            row = _job(supabase, job_id)
            if row and row.get("status") in ("claimed", "streaming", "complete"):
                claimed = True
            elif now > deadline:
                # Nobody picked it up. Abandon and let the caller buy instead.
                try:
                    supabase.table("jobs").update(
                        {"status": "abandoned", "error": "unclaimed"}
                    ).eq("id", job_id).eq("status", "pending").execute()
                except Exception:
                    logger.warning("abandon_failed job=%s", job_id, exc_info=True)
                raise MeshUnavailable("unclaimed", f"no node claimed within {DISPATCH_DEADLINE_S}s")
            else:
                time.sleep(poll_s)
                continue

        chunks = _chunks_after(supabase, job_id, seq)
        for c in chunks:
            seq = max(seq, c["seq"])
            if ttft_ms is None:
                ttft_ms = int((time.perf_counter() - t0) * 1000)
            parts.append(c["content"])
            yield ("delta", c["content"], {})

        row = _job(supabase, job_id)
        status = (row or {}).get("status")

        if status == "complete":
            text = (row.get("output") or "").strip() or "".join(parts)
            # Trailing chunks can land after the completion write.
            for c in _chunks_after(supabase, job_id, seq):
                seq = max(seq, c["seq"])
                parts.append(c["content"])
                yield ("delta", c["content"], {})
            full = "".join(parts) or text
            meta = {
                "model": row.get("model") or MESH_MODEL,
                "served_by": row.get("served_by"),
                "node_id": row.get("node_id"),
                "tokens": int(row.get("completion_tokens") or row.get("tokens_served") or 0)
                          or max(1, len(full) // 4),
                "latency_ms": int(row.get("latency_ms") or (time.perf_counter() - t0) * 1000),
                "ttft_ms": row.get("ttft_ms") or ttft_ms,
                "sovereign": True,
            }
            yield ("done", full, meta)
            return

        if status in ("error", "expired", "abandoned"):
            raise MeshUnavailable("node_error", (row or {}).get("error") or status)

        if time.perf_counter() > hard_deadline:
            raise MeshUnavailable("node_error", "lease exceeded without completion")

        if not chunks:
            time.sleep(poll_s)


def _job(supabase, job_id: str) -> dict | None:
    try:
        r = supabase.table("jobs").select("*").eq("id", job_id).limit(1).execute()
        return (r.data or [None])[0]
    except Exception:
        logger.warning("job_poll_failed job=%s", job_id, exc_info=True)
        return None


def _chunks_after(supabase, job_id: str, seq: int) -> list[dict]:
    try:
        r = (
            supabase.table("job_chunks")
            .select("seq,content")
            .eq("job_id", job_id)
            .gt("seq", seq)
            .order("seq")
            .limit(200)
            .execute()
        )
        return r.data or []
    except Exception:
        return []


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------

def record(
    supabase,
    *,
    target: str,
    tokens: int,
    user_id: str | None = None,
    job_id: str | None = None,
    node_id: str | None = None,
    model: str | None = None,
    reason: str | None = None,
    latency_ms: int | None = None,
    ttft_ms: int | None = None,
) -> None:
    """Write one routing event.

    This is the only place sovereignty is measured, so it must never raise into
    the request path — a failed metric write must not cost a user their answer.
    """
    mtok = max(tokens, 0) / 1_000_000
    row = {
        "user_id": user_id,
        "job_id": job_id,
        "target": target,
        "node_id": node_id,
        "model": model,
        "reason": reason if target == "fallback" else None,
        "tokens": max(tokens, 0),
        "latency_ms": latency_ms,
        "ttft_ms": ttft_ms,
        "cost_usd": round(mtok * FALLBACK_USD_PER_MTOK, 6) if target == "fallback" else 0,
        "credits": round(mtok * MESH_CREDIT_PER_MTOK, 6) if target == "mesh" else 0,
    }
    try:
        supabase.table("routing_events").insert(row).execute()
    except Exception:
        logger.warning("routing_event_write_failed target=%s reason=%s",
                       target, reason, exc_info=True)

    if target == "mesh" and node_id:
        try:
            supabase.rpc("credit_provider", {
                "p_node_id": node_id,
                "p_tokens": max(tokens, 0),
                "p_credits": row["credits"],
            }).execute()
        except Exception:
            # The RPC is optional; routing_events is the source of truth for
            # payouts either way.
            logger.debug("credit_provider_rpc_absent", exc_info=True)


def sovereignty(supabase, days: int = 1) -> dict:
    """Current mesh share and what the remainder cost."""
    try:
        r = supabase.table("sovereignty_daily").select("*").limit(days).execute()
        rows = r.data or []
    except Exception:
        return {"mesh_share": None, "available": False}

    if not rows:
        return {"mesh_share": None, "available": True, "turns": 0}

    today = rows[0]
    return {
        "available": True,
        "day": today.get("day"),
        "turns": today.get("turns", 0),
        "mesh_turns": today.get("mesh_turns", 0),
        "tokens": today.get("tokens", 0),
        "mesh_tokens": today.get("mesh_tokens", 0),
        "mesh_share": float(today.get("mesh_share") or 0),
        "fallback_cost_usd": float(today.get("fallback_cost_usd") or 0),
        "provider_credits": float(today.get("provider_credits") or 0),
        "top_fallback_reason": today.get("top_fallback_reason"),
        "history": [
            {"day": r.get("day"), "mesh_share": float(r.get("mesh_share") or 0),
             "tokens": r.get("tokens", 0),
             "fallback_cost_usd": float(r.get("fallback_cost_usd") or 0)}
            for r in rows
        ],
    }


def fallback_reasons(supabase) -> list[dict]:
    try:
        r = supabase.table("fallback_reasons_7d").select("*").limit(10).execute()
        return r.data or []
    except Exception:
        return []
