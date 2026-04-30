from __future__ import annotations
import os
import stripe
from fastapi import HTTPException
from app.lib.logger import get_logger
from app.models.schemas import UsageRecord

logger = get_logger(__name__)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_FREE_PRICE_ID = os.getenv("STRIPE_FREE_PRICE_ID", "price_free")
STRIPE_PRO_PRICE_ID = os.getenv("STRIPE_PRO_PRICE_ID", "price_pro")
STRIPE_ADMIN_PRICE_ID = os.getenv("STRIPE_ADMIN_PRICE_ID", "price_admin")

PRICE_TIER_MAP: dict[str, str] = {}

def _build_price_tier_map() -> None:
    PRICE_TIER_MAP[STRIPE_FREE_PRICE_ID] = "free"
    PRICE_TIER_MAP[STRIPE_PRO_PRICE_ID] = "pro"
    PRICE_TIER_MAP[STRIPE_ADMIN_PRICE_ID] = "admin"

_build_price_tier_map()

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


def verify_stripe_signature(payload: bytes, sig_header: str) -> dict:
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        return dict(event)
    except Exception as exc:
        logger.warning("stripe_sig_invalid", error=str(exc))
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")


def get_tier_for_price(price_id: str) -> str:
    return PRICE_TIER_MAP.get(price_id, "free")


async def handle_subscription_event(event: dict, redis_client) -> str:
    sub = event.get("data", {}).get("object", {})
    customer_id = sub.get("customer", "")
    items = sub.get("items", {}).get("data", [])
    price_id = items[0].get("price", {}).get("id", "") if items else ""
    new_tier = get_tier_for_price(price_id)
    event_type = event.get("type", "")

    if not customer_id:
        return "no_key_found"

    try:
        customer = stripe.Customer.retrieve(customer_id)
        email = customer.get("email", "")
    except Exception:
        return "no_key_found"

    if not email:
        return "no_key_found"

    key_hash = await redis_client.get(f"billing:email:{email}")
    if not key_hash:
        return "no_key_found"

    if isinstance(key_hash, bytes):
        key_hash = key_hash.decode()

    old_data = await redis_client.hgetall(f"auth:keys:{key_hash}")
    old_tier = old_data.get(b"tier", b"free").decode() if old_data else "free"

    if event_type == "customer.subscription.deleted":
        await redis_client.hset(f"auth:keys:{key_hash}", "tier", "free")
        return "cancelled"

    await redis_client.hset(f"auth:keys:{key_hash}", "tier", new_tier)

    tier_order = {"free": 0, "pro": 1, "admin": 2}
    if tier_order.get(new_tier, 0) > tier_order.get(old_tier, 0):
        return "upgraded"
    elif tier_order.get(new_tier, 0) < tier_order.get(old_tier, 0):
        return "downgraded"
    return "upgraded"


async def record_usage(redis_client, key_hash: str, tokens: int) -> None:
    await redis_client.hincrby(f"usage:{key_hash}", "requests", 1)
    await redis_client.hincrby(f"usage:{key_hash}", "tokens_total", tokens)
    await redis_client.expire(f"usage:{key_hash}", 2592000)


async def get_usage(redis_client, key_hash: str) -> UsageRecord:
    data = await redis_client.hgetall(f"usage:{key_hash}")
    requests = int(data.get(b"requests", 0) if data else 0)
    tokens_total = int(data.get(b"tokens_total", 0) if data else 0)
    return UsageRecord(key_hash=key_hash, requests=requests, tokens_total=tokens_total)
