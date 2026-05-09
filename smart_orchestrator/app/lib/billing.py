from __future__ import annotations
import os
import json
from datetime import datetime, timezone
from typing import Any

import stripe
from fastapi import HTTPException
from app.config import APP_BASE_URL, STRIPE_BETA_PRICE_ID, STRIPE_MODE
from app.lib.analytics import track_event
from app.lib.email import render_template, send_email
from app.lib.logger import get_logger
from app.models.schemas import UsageRecord

logger = get_logger(__name__)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_FREE_PRICE_ID = os.getenv("STRIPE_FREE_PRICE_ID", "price_free")
STRIPE_PRO_PRICE_ID = os.getenv("STRIPE_PRO_PRICE_ID", "price_pro")
STRIPE_ADMIN_PRICE_ID = os.getenv("STRIPE_ADMIN_PRICE_ID", "price_admin")
BETA_PLAN = {
    "id": "neuralmesh_beta",
    "name": "NeuralMesh Beta",
    "price_monthly_usd": 19,
    "daily_requests": 5000,
    "features": ["5000 requests/day", "priority routing"],
}

# ---------------------------------------------------------------------------
# STRIPE_MODE: mock | test | live
# Set to 'mock' in unit tests to bypass real Stripe calls.
# Set to 'test' to hit Stripe test-mode endpoints (requires sk_test_ key).
# Set to 'live' in production (requires sk_live_ key).
# ---------------------------------------------------------------------------
STRIPE_MODE = os.getenv("STRIPE_MODE", "mock").lower()

def log_stripe_mode_banner() -> None:
    """Log a startup banner so the mode is never ambiguous."""
    banners = {
        "mock": "[STRIPE] Mode: MOCK  Stripe calls bypassed (unit-test safe)",
        "test": "[STRIPE] Mode: TEST  Using Stripe test-mode keys",
        "live": "[STRIPE] *** Mode: LIVE ***  Real money transactions enabled",
    }
    msg = banners.get(STRIPE_MODE, f"[STRIPE] Mode: {STRIPE_MODE.upper()} (unrecognised)")
    logger.info(msg)


PRICE_TIER_MAP: dict[str, str] = {}

def _build_price_tier_map() -> None:
    PRICE_TIER_MAP[STRIPE_FREE_PRICE_ID] = "free"
    PRICE_TIER_MAP[STRIPE_PRO_PRICE_ID] = "pro"
    PRICE_TIER_MAP[STRIPE_ADMIN_PRICE_ID] = "admin"

_build_price_tier_map()

PRICE_TIER_MAP[STRIPE_BETA_PRICE_ID] = "beta"

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


def verify_stripe_signature(payload: bytes, sig_header: str) -> dict:
    if STRIPE_MODE == "mock" and sig_header == "mock":
        return json.loads(payload.decode("utf-8"))
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        return dict(event)
    except Exception as exc:
        logger.warning("stripe_sig_invalid", error=str(exc))
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")


def get_tier_for_price(price_id: str) -> str:
    return PRICE_TIER_MAP.get(price_id, "free")


def _period_end_iso(subscription: dict[str, Any]) -> str | None:
    period_end = subscription.get("current_period_end")
    if not period_end:
        return None
    try:
        return datetime.fromtimestamp(int(period_end), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


async def create_beta_checkout_session(user: dict[str, Any]) -> str:
    if STRIPE_MODE == "mock" or not STRIPE_SECRET_KEY:
        return f"{APP_BASE_URL}/account.html?checkout=mock"
    if not STRIPE_BETA_PRICE_ID:
        raise HTTPException(status_code=500, detail="STRIPE_BETA_PRICE_ID is not configured")

    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        customer = stripe.Customer.create(email=user.get("email"), metadata={"user_id": user["id"]})
        customer_id = customer["id"]

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=user["id"],
        line_items=[{"price": STRIPE_BETA_PRICE_ID, "quantity": 1}],
        success_url=f"{APP_BASE_URL}/account.html?checkout=success",
        cancel_url=f"{APP_BASE_URL}/account.html?checkout=cancelled",
        metadata={"user_id": user["id"]},
        subscription_data={"metadata": {"user_id": user["id"]}},
    )
    return session["url"]


async def create_customer_portal_session(user: dict[str, Any]) -> str:
    if STRIPE_MODE == "mock" or not STRIPE_SECRET_KEY:
        return f"{APP_BASE_URL}/account.html?portal=mock"
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer for this account")
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{APP_BASE_URL}/account.html",
    )
    return session["url"]


def list_invoice_history(user: dict[str, Any]) -> list[dict[str, Any]]:
    if STRIPE_MODE == "mock" or not STRIPE_SECRET_KEY or not user.get("stripe_customer_id"):
        return []
    invoices = stripe.Invoice.list(customer=user["stripe_customer_id"], limit=10)
    return [
        {
            "id": invoice["id"],
            "hosted_invoice_url": invoice.get("hosted_invoice_url"),
            "amount_paid": invoice.get("amount_paid", 0),
            "status": invoice.get("status"),
            "created": invoice.get("created"),
        }
        for invoice in invoices.get("data", [])
    ]


async def handle_subscription_event(event: dict, redis_client=None, store=None) -> str:
    if store is not None:
        action = await _handle_beta_subscription_event(event, store)
        if action != "ignored":
            return action

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


async def _handle_beta_subscription_event(event: dict, store) -> str:
    event_type = event.get("type", "")
    obj = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        user_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("user_id")
        if not user_id:
            return "no_user_found"
        subscription_id = obj.get("subscription")
        update = {
            "subscription_status": "active",
            "stripe_customer_id": obj.get("customer"),
            "stripe_subscription_id": subscription_id,
        }
        if subscription_id and STRIPE_SECRET_KEY and STRIPE_MODE != "mock":
            subscription = stripe.Subscription.retrieve(subscription_id)
            update["subscription_current_period_end"] = _period_end_iso(subscription)
        await store.update_user(user_id, update)
        await track_event("subscription", user_id, {"source": "checkout.session.completed"})
        profile = await store.get_profile(user_id)
        if profile and profile.get("email"):
            await send_email(
                profile["email"],
                "Your NeuralMesh Beta subscription is active",
                render_template("subscription-receipt.html"),
            )
        return "subscription_active"

    if event_type in {"customer.subscription.updated", "customer.subscription.deleted"}:
        customer_id = obj.get("customer")
        if not customer_id:
            return "no_user_found"
        status = "none" if event_type == "customer.subscription.deleted" else obj.get("status", "active")
        if status in {"active", "trialing"}:
            subscription_status = "active"
        elif status in {"past_due", "unpaid"}:
            subscription_status = "past_due"
        else:
            subscription_status = "none"
        updated = await store.update_user_by_customer(
            customer_id,
            {
                "subscription_status": subscription_status,
                "stripe_subscription_id": obj.get("id"),
                "subscription_current_period_end": _period_end_iso(obj),
            },
        )
        if updated:
            await track_event("subscription", updated["id"], {"status": subscription_status})
        return "subscription_updated" if updated else "no_user_found"

    return "ignored"


async def record_usage(redis_client, key_hash: str, tokens: int) -> None:
    await redis_client.hincrby(f"usage:{key_hash}", "requests", 1)
    await redis_client.hincrby(f"usage:{key_hash}", "tokens_total", tokens)
    await redis_client.expire(f"usage:{key_hash}", 2592000)


async def get_usage(redis_client, key_hash: str) -> UsageRecord:
    data = await redis_client.hgetall(f"usage:{key_hash}")
    requests = int(data.get(b"requests", 0) if data else 0)
    tokens_total = int(data.get(b"tokens_total", 0) if data else 0)
    return UsageRecord(key_hash=key_hash, requests=requests, tokens_total=tokens_total)
