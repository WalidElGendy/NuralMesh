
from __future__ import annotations
import os
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "NeuralMesh <noreply@neuralmesh.ai>")
RESEND_BASE_URL = "https://api.resend.com"

async def send_email(to: str, subject: str, html: str) -> bool:
    """
    Send an email using Resend API.
    Returns True on success, False on failure.
    If RESEND_API_KEY is not set, logs a warning and returns True (no-op).
    """
    if not RESEND_API_KEY:
        logger.warning("[EMAIL] RESEND_API_KEY not set  skipping email to %s", to)
        return True
    payload = {"from": EMAIL_FROM, "to": [to], "subject": subject, "html": html}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{RESEND_BASE_URL}/emails",
                json=payload,
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            )
        if resp.status_code in (200, 201):
            logger.info("[EMAIL] Sent to %s subject=%r", to, subject)
            return True
        logger.warning("[EMAIL] Failed status=%s body=%s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        logger.warning("[EMAIL] Exception sending to %s: %s", to, exc)
        return False
