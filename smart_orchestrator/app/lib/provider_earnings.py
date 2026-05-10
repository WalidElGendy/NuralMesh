"""
GPU Provider Earnings Ledger.

Tracks USD earnings owed to each GPU provider node based on compute served.
Payments are made in USD via bank transfer (Stripe Connect / ACH / wire).
No crypto, no tokens  real money for real work.

Earnings model:
  - Per 1000 sovereign-node tokens processed: 1 beta credit
  - Accrued in Redis; queued for payout on provider request
  - Admin approves payout -> Stripe Transfer API called

Redis key layout:
  provider:earnings:{node_id}       HASH: total_usd, total_tokens, pending_usd, lifetime_usd
  provider:payout_requests          SORTED SET: node_id -> timestamp (pending requests)
  provider:payout:{payout_id}       STRING: JSON payout record
"""
import json
import time
import uuid
import logging
from typing import Optional

logger = logging.getLogger(__name__)

CREDITS_PER_1K_TOKENS = 1.0

PAYOUT_MIN_USD = 1.00     # Minimum payout threshold
PAYOUT_REQUEST_KEY = "provider:payout_requests"
PROVIDER_EARNINGS_KEY = "provider:earnings:{node_id}"
PAYOUT_RECORD_KEY = "provider:payout:{payout_id}"
PAYOUT_RECORD_TTL = 90 * 24 * 3600  # 90 days


def _compute_earnings_usd(tokens: int, model: str) -> float:
    """Legacy compatibility shim; beta earnings are credits, not USD."""

    return _compute_earnings_credits(tokens)


def _compute_earnings_credits(tokens: int) -> float:
    """Calculate beta provider credits for sovereign-node tokens."""

    return round((tokens / 1000.0) * CREDITS_PER_1K_TOKENS, 8)


async def accrue_earnings(redis_client, node_id: str, tokens: int, model: str) -> float:
    """
    Accrue beta credits for a node after completing an inference job.
    Returns the credits accrued this call.
    """
    if tokens <= 0:
        return 0.0

    earned_credits = _compute_earnings_credits(tokens)
    key = PROVIDER_EARNINGS_KEY.format(node_id=node_id)

    # Pipeline: increment all counters atomically
    pipe = redis_client.pipeline()
    pipe.hincrbyfloat(key, "total_credits", earned_credits)
    pipe.hincrbyfloat(key, "pending_credits", earned_credits)
    pipe.hincrbyfloat(key, "lifetime_credits", earned_credits)
    pipe.hincrbyfloat(key, "total_usd", earned_credits)
    pipe.hincrbyfloat(key, "pending_usd", earned_credits)
    pipe.hincrbyfloat(key, "lifetime_usd", earned_credits)
    pipe.hincrby(key, "total_tokens", tokens)
    await pipe.execute()

    logger.debug(
        "Earnings: node %s accrued %.8f credits for %d tokens (%s)",
        node_id,
        earned_credits,
        tokens,
        model,
    )
    return earned_credits


async def get_provider_earnings(redis_client, node_id: str) -> dict:
    """Return current earnings summary for a provider node."""
    key = PROVIDER_EARNINGS_KEY.format(node_id=node_id)
    raw = await redis_client.hgetall(key)
    if not raw:
        return {
            "node_id": node_id,
            "total_credits": 0.0,
            "pending_credits": 0.0,
            "lifetime_credits": 0.0,
            "total_usd": 0.0,
            "pending_usd": 0.0,
            "lifetime_usd": 0.0,
            "total_tokens": 0,
        }

    def _f(k, default=0.0):
        v = raw.get(k.encode(), raw.get(k, None))
        if v is None:
            return default
        return float(v.decode() if isinstance(v, bytes) else v)

    def _i(k):
        v = raw.get(k.encode(), raw.get(k, None))
        if v is None:
            return 0
        return int(float(v.decode() if isinstance(v, bytes) else v))

    return {
        "node_id": node_id,
        "total_credits": _f("total_credits", _f("total_usd")),
        "pending_credits": _f("pending_credits", _f("pending_usd")),
        "lifetime_credits": _f("lifetime_credits", _f("lifetime_usd")),
        "total_usd": _f("total_usd"),
        "pending_usd": _f("pending_usd"),
        "lifetime_usd": _f("lifetime_usd"),
        "total_tokens": _i("total_tokens"),
    }


async def request_payout(
    redis_client,
    node_id: str,
    bank_account_name: str,
    bank_iban_or_account: str,
    bank_routing_or_swift: str,
) -> Optional[dict]:
    """
    Provider requests a USD payout via bank transfer.
    Returns payout record if eligible, None if pending_usd < minimum.
    """
    earnings = await get_provider_earnings(redis_client, node_id)
    pending = earnings["pending_usd"]

    if pending < PAYOUT_MIN_USD:
        logger.info("Payout request from %s denied: $%.4f < minimum $%.2f", node_id, pending, PAYOUT_MIN_USD)
        return None

    payout_id = str(uuid.uuid4())
    record = {
        "payout_id": payout_id,
        "node_id": node_id,
        "amount_usd": pending,
        "bank_account_name": bank_account_name,
        "bank_iban_or_account": bank_iban_or_account,
        "bank_routing_or_swift": bank_routing_or_swift,
        "status": "pending",
        "requested_at": time.time(),
        "approved_at": None,
        "stripe_transfer_id": None,
    }

    # Store payout record
    payout_key = PAYOUT_RECORD_KEY.format(payout_id=payout_id)
    await redis_client.set(payout_key, json.dumps(record), ex=PAYOUT_RECORD_TTL)

    # Add to pending set (score = timestamp for ordering)
    await redis_client.zadd(PAYOUT_REQUEST_KEY, {payout_id: time.time()})

    # Freeze the pending amount (move to "in-flight")
    earnings_key = PROVIDER_EARNINGS_KEY.format(node_id=node_id)
    await redis_client.hset(earnings_key, "pending_usd", 0.0)

    logger.info("Payout request %s created for node %s: $%.4f", payout_id, node_id, pending)
    return record


async def list_pending_payouts(redis_client, limit: int = 50) -> list[dict]:
    """Return list of pending payout records (oldest first)."""
    payout_ids = await redis_client.zrange(PAYOUT_REQUEST_KEY, 0, limit - 1)
    records = []
    for pid in payout_ids:
        pid_str = pid.decode() if isinstance(pid, bytes) else pid
        raw = await redis_client.get(PAYOUT_RECORD_KEY.format(payout_id=pid_str))
        if raw:
            records.append(json.loads(raw.decode() if isinstance(raw, bytes) else raw))
    return records


async def approve_payout(redis_client, payout_id: str, stripe_transfer_id: str) -> Optional[dict]:
    """
    Mark a payout as approved and record the Stripe transfer ID.
    Called by admin after initiating the bank transfer via Stripe.
    """
    payout_key = PAYOUT_RECORD_KEY.format(payout_id=payout_id)
    raw = await redis_client.get(payout_key)
    if raw is None:
        return None

    record = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    record["status"] = "approved"
    record["approved_at"] = time.time()
    record["stripe_transfer_id"] = stripe_transfer_id

    await redis_client.set(payout_key, json.dumps(record), ex=PAYOUT_RECORD_TTL)
    # Remove from pending set
    await redis_client.zrem(PAYOUT_REQUEST_KEY, payout_id)

    logger.info("Payout %s approved (Stripe transfer %s)", payout_id, stripe_transfer_id)
    return record
