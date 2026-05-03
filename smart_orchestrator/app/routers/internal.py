
from __future__ import annotations
import os
import pathlib
import logging
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from app.lib.email import send_email

logger = logging.getLogger(__name__)
router = APIRouter()

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

def _verify_internal_key(x_internal_key: str | None) -> None:
    """Reject requests without valid X-Internal-Key header."""
    if not INTERNAL_API_KEY:
        # If key not configured, refuse all internal calls
        raise HTTPException(status_code=503, detail="INTERNAL_API_KEY not configured")
    if x_internal_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid X-Internal-Key")

class NotifyRequest(BaseModel):
    email: str
    kind: str  # "user" | "provider"

@router.post("/internal/notify-waitlist")
async def notify_waitlist(payload: NotifyRequest, x_internal_key: str | None = Header(None)) -> dict:
    """Called by Supabase trigger when a new waitlist row is inserted."""
    _verify_internal_key(x_internal_key)
    template_dir = pathlib.Path("app/templates")
    if payload.kind == "provider":
        subject = "Thanks for offering your GPU  NeuralMesh"
        html_path = template_dir / "waitlist_provider_welcome.html"
    else:
        subject = "You're on the NeuralMesh waitlist!"
        html_path = template_dir / "waitlist_user_welcome.html"
    html = html_path.read_text() if html_path.exists() else f"<p>Welcome, {payload.email}!</p>"
    sent = await send_email(payload.email, subject, html)
    return {"sent": sent, "email": payload.email, "kind": payload.kind}
