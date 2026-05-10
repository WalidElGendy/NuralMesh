"""
Provider Earnings & Payout API.

GPU providers use these endpoints to:
  - View their USD earnings (tokens processed * rate)
  - Request a USD bank transfer payout

Authentication: X-Api-Key header (provider uses the same API key tied to their node_id).
"""
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.stages.cache import get_redis_client
from app.lib.auth import verify_api_key
from app.lib.provider_earnings import (
    get_provider_earnings,
    request_payout,
    PAYOUT_MIN_USD,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/provider", tags=["provider"])


class PayoutRequestBody(BaseModel):
    node_id: str
    bank_account_name: str
    bank_iban_or_account: str       # IBAN (EU) or account number (US)
    bank_routing_or_swift: str      # Routing number (US) or SWIFT/BIC (international)


class PayoutResponse(BaseModel):
    payout_id: Optional[str] = None
    node_id: str
    amount_usd: float
    status: str       # "queued" | "below_minimum"
    message: str


@router.get("/earnings/{node_id}")
async def provider_earnings(
    node_id: str,
    x_api_key: Optional[str] = Header(None),
):
    """
    Get USD earnings summary for a GPU provider node.
    Returns total_usd, pending_usd, lifetime_usd, total_tokens.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-Api-Key header required")

    redis = await get_redis_client()
    try:
        await verify_api_key(x_api_key, redis)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return await get_provider_earnings(redis, node_id)


@router.post("/payout", response_model=PayoutResponse)
async def request_provider_payout(
    body: PayoutRequestBody,
    x_api_key: Optional[str] = Header(None),
):
    """
    Request a USD bank transfer payout for pending earnings.
    Minimum payout is $1.00 USD.
    Bank details are stored for admin to process the transfer via Stripe.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-Api-Key header required")

    redis = await get_redis_client()
    try:
        await verify_api_key(x_api_key, redis)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid API key")

    record = await request_payout(
        redis,
        node_id=body.node_id,
        bank_account_name=body.bank_account_name,
        bank_iban_or_account=body.bank_iban_or_account,
        bank_routing_or_swift=body.bank_routing_or_swift,
    )

    if record is None:
        return PayoutResponse(
            payout_id=None,
            node_id=body.node_id,
            amount_usd=0.0,
            status="below_minimum",
            message=f"Pending balance below minimum payout threshold (${PAYOUT_MIN_USD:.2f} USD)",
        )

    return PayoutResponse(
        payout_id=record["payout_id"],
        node_id=body.node_id,
        amount_usd=record["amount_usd"],
        status="queued",
        message="Payout request queued. Bank transfer will be processed within 3-5 business days.",
    )
