"""
Admin Payout Approval API.

Admins review pending provider payout requests and approve them.
On approval, a Stripe Transfer is initiated to send USD to the provider's bank.

Stripe Connect flow:
  - Each provider must have a Stripe Connect account (created at onboarding).
  - Admin calls POST /admin/payouts/{payout_id}/approve with the stripe_account_id.
  - We call stripe.Transfer.create() to push funds to their connected account.
  - Stripe then handles the ACH/wire to the provider's bank account.
"""
import os
import logging
from typing import Optional

import stripe
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.stages.cache import get_redis_client
from app.lib.provider_earnings import list_pending_payouts, approve_payout

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/payouts", tags=["admin"])

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "dev-admin-secret")


def _check_admin(secret: Optional[str]):
    if not secret or secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin access required")


class ApprovePayoutBody(BaseModel):
    stripe_account_id: str     # Provider's Stripe Connect account ID (acct_xxx)
    note: Optional[str] = None


class ApprovePayoutResponse(BaseModel):
    payout_id: str
    node_id: str
    amount_usd: float
    stripe_transfer_id: str
    status: str


@router.get("/pending")
async def list_payouts(
    x_admin_secret: Optional[str] = Header(None),
    limit: int = 50,
):
    """List all pending provider payout requests (admin only)."""
    _check_admin(x_admin_secret)
    redis = await get_redis_client()
    return await list_pending_payouts(redis, limit=limit)


@router.post("/{payout_id}/approve", response_model=ApprovePayoutResponse)
async def approve(
    payout_id: str,
    body: ApprovePayoutBody,
    x_admin_secret: Optional[str] = Header(None),
):
    """
    Approve a provider payout and initiate a Stripe bank transfer.
    Requires the provider's Stripe Connect account ID.
    """
    _check_admin(x_admin_secret)
    redis = await get_redis_client()

    # Retrieve the pending payout to get amount
    from app.lib.provider_earnings import PAYOUT_RECORD_KEY
    import json
    raw = await redis.get(PAYOUT_RECORD_KEY.format(payout_id=payout_id))
    if raw is None:
        raise HTTPException(status_code=404, detail="Payout not found")

    record = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    if record["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Payout already {record['status']}")

    amount_cents = int(record["amount_usd"] * 100)
    if amount_cents < 1:
        raise HTTPException(status_code=400, detail="Amount too small to transfer")

    # Initiate Stripe Transfer to provider's connected account
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    try:
        transfer = stripe.Transfer.create(
            amount=amount_cents,
            currency="usd",
            destination=body.stripe_account_id,
            description=f"NeuralMesh GPU provider payout  {record['node_id']}",
            metadata={
                "payout_id": payout_id,
                "node_id": record["node_id"],
                "note": body.note or "",
            },
        )
        stripe_transfer_id = transfer["id"]
    except stripe.StripeError as e:
        logger.error("Stripe transfer failed for payout %s: %s", payout_id, e)
        raise HTTPException(status_code=502, detail=f"Stripe transfer failed: {e.user_message}")

    # Mark approved in Redis
    updated = await approve_payout(redis, payout_id, stripe_transfer_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update payout record")

    return ApprovePayoutResponse(
        payout_id=payout_id,
        node_id=record["node_id"],
        amount_usd=record["amount_usd"],
        stripe_transfer_id=stripe_transfer_id,
        status="approved",
    )
