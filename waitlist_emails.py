"""Transactional waitlist emails for MeshNet (Resend).

Auto-issues a beta activation code and emails it to the new signup.
GPU providers get node-activation steps; AI users get a node-availability
snapshot and can start sending jobs right away.
"""
import logging
import os
import secrets
from datetime import timedelta

import requests

logger = logging.getLogger("meshnet.waitlist_emails")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "MeshNet <noreply@meshnet.co>")
BETA_BASE_URL = os.environ.get("BETA_BASE_URL", "https://beta.meshnet.co").rstrip("/")


def count_nodes_online(supabase, isoformat, utc_now) -> int:
    """Providers seen in the last 5 minutes (matches admin stats logic)."""
    try:
        five_min_ago = isoformat(utc_now() - timedelta(minutes=5))
        q = (
            supabase.table("providers")
            .select("node_id", count="exact")
            .gte("last_seen_at", five_min_ago)
            .execute()
        )
        return q.count or 0
    except Exception as error:
        logger.warning("count_nodes_online failed error=%s", error)
        return 0


def generate_invite_code(supabase, intent: str, email: str):
    """Create a unique activation code in the invites table for this signup."""
    for _ in range(5):
        code = f"NMESH-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
        try:
            result = (
                supabase.table("invites")
                .insert({
                    "code": code,
                    "intent": intent,
                    "email": email,
                    "notes": f"Auto-issued via waitlist ({intent})",
                })
                .execute()
            )
            if result.data:
                return code
        except Exception as error:
            logger.warning("invite insert retry intent=%s error=%s", intent, error)
    return None


def send_email(to_email: str, subject: str, html: str) -> bool:
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set; skipping email to %s", to_email)
        return False
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"from": EMAIL_FROM, "to": [to_email], "subject": subject, "html": html},
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.warning("Resend error %s: %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as error:
        logger.warning("send_email failed to=%s error=%s", to_email, error)
        return False


def _code_box(code: str) -> str:
    return (
        f'<p style="font-size:20px;font-weight:bold;letter-spacing:2px;'
        f'background:#f4f4f5;padding:12px 16px;border-radius:8px;'
        f'display:inline-block">{code}</p>'
    )


def provider_email_html(name: str, code: str, signup_url: str) -> str:
    greeting = f"Hi {name}," if name else "Hi,"
    return f"""\
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;color:#111">
  <h2>Welcome to the MeshNet GPU Provider beta</h2>
  <p>{greeting}</p>
  <p>You're in. Your GPU can now start earning on the MeshNet network.</p>
  <p><strong>Your activation code:</strong></p>
  {_code_box(code)}
  <h3>How to activate your node</h3>
  <ol>
    <li>Open the beta dashboard and create your provider account:
        <a href="{signup_url}">{signup_url}</a></li>
    <li>Enter the activation code above when prompted.</li>
    <li>Download and run the node installer for your machine.</li>
    <li>Your node registers automatically and appears as <strong>online</strong>
        once it sends its first heartbeat.</li>
  </ol>
  <p>Once online, jobs route to your GPU automatically and earnings accrue in USD.</p>
  <p style="color:#666;font-size:12px">If you didn't request this, ignore this email.</p>
</div>"""


def user_email_html(name: str, code: str, signup_url: str, nodes_online: int) -> str:
    greeting = f"Hi {name}," if name else "Hi,"
    if nodes_online > 0:
        availability = (
            f"There are currently <strong>{nodes_online}</strong> GPU node(s) "
            "online and ready to serve your jobs."
        )
    else:
        availability = (
            "Nodes are coming online continuously - you'll be able to run jobs "
            "as soon as providers connect."
        )
    return f"""\
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;color:#111">
  <h2>Welcome to the MeshNet AI beta</h2>
  <p>{greeting}</p>
  <p>You now have early access to cheap, verified AI inference on MeshNet.</p>
  <p><strong>Your activation code:</strong></p>
  {_code_box(code)}
  <h3>Getting started</h3>
  <ol>
    <li>Create your account here: <a href="{signup_url}">{signup_url}</a></li>
    <li>Enter the activation code above when prompted.</li>
    <li>You can start sending jobs right away - submit a job and the network
        routes it to the best available GPU, verified on-chain.</li>
  </ol>
  <p><strong>Network status:</strong> {availability}</p>
  <p style="color:#666;font-size:12px">If you didn't request this, ignore this email.</p>
</div>"""


def handle_waitlist_signup(supabase, isoformat, utc_now, kind: str, email: str, name: str):
    """Generate an activation code and send the role-specific welcome email.

    Safe to call inside the /api/waitlist handler; never raises.
    """
    try:
        code = generate_invite_code(supabase, kind, email)
        if not code:
            return
        if kind == "provider":
            url = f"{BETA_BASE_URL}/signup.html?intent=provider&invite={code}"
            send_email(email, "Your MeshNet GPU Provider beta access",
                       provider_email_html(name, code, url))
        else:
            url = f"{BETA_BASE_URL}/signup.html?intent=user&invite={code}"
            nodes_online = count_nodes_online(supabase, isoformat, utc_now)
            send_email(email, "Your MeshNet AI beta access",
                       user_email_html(name, code, url, nodes_online))
    except Exception as error:
        logger.warning("handle_waitlist_signup failed email=%s error=%s", email, error)
