from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from app.lib.billing import verify_stripe_signature, handle_subscription_event
from app.lib.logger import get_logger
from app.stages.cache import get_redis_client
from app.models.schemas import StripeWebhookResponse

logger = get_logger(__name__)
router = APIRouter()

SUBSCRIPTION_EVENTS = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}


@router.post("/stripe", response_model=StripeWebhookResponse)
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
    
    event = verify_stripe_signature(payload, sig_header)
    event_type = event.get("type", "")
    
    if event_type not in SUBSCRIPTION_EVENTS:
        logger.info("stripe_webhook_ignored", event_type=event_type)
        return StripeWebhookResponse(received=True, action="ignored")
    
    redis = await get_redis_client()
    action = await handle_subscription_event(event, redis)
    logger.info("stripe_webhook_processed", event_type=event_type, action=action)
    return StripeWebhookResponse(received=True, action=action)
