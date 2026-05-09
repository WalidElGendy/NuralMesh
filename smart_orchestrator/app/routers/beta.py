from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config import ADMIN_SECRET, BETA_INVITE_REQUIRED, BETA_PROVIDER_TERMS_VERSION
from app.lib.analytics import track_event
from app.lib.beta_auth import (
    clear_session_cookies,
    current_session_user,
    get_auth_client,
    require_csrf,
    set_session_cookies,
)
from app.lib.beta_store import get_beta_store, trial_is_active
from app.lib.billing import (
    BETA_PLAN,
    create_beta_checkout_session,
    create_customer_portal_session,
    list_invoice_history,
)
from app.lib.email import send_provider_welcome, send_signup_confirm
from app.models.schemas import ChatMessage, ChatRequest
from app.pipeline import run_pipeline

router = APIRouter(prefix="/api", tags=["beta"])


class SignupRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    invite_code: str | None = None
    intent: Literal["user", "provider"] = "user"


class LoginRequest(BaseModel):
    email: str
    password: str | None = None
    magic_link: bool = False


class BetaChatRequest(BaseModel):
    messages: list[ChatMessage]
    system: str | None = None
    stream: bool = True


class SeedInvitesRequest(BaseModel):
    count: int = Field(default=10, ge=1, le=100)
    created_by: str = "admin"


@router.post("/auth/signup")
async def signup(payload: SignupRequest) -> dict[str, object]:
    if BETA_INVITE_REQUIRED and not payload.invite_code:
        raise HTTPException(status_code=400, detail="Invite code is required")

    auth_client = get_auth_client()
    auth_response = await auth_client.signup(payload.email, payload.password, payload.intent)
    user = auth_response.get("user") or {}
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=502, detail="Supabase Auth did not return a user")

    store = get_beta_store()
    if payload.invite_code:
        try:
            await store.claim_invite_and_mint_children(payload.invite_code, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    await store.create_profile(user_id, payload.email, payload.intent, payload.invite_code)
    await track_event("signup", user_id, {"intent": payload.intent})

    confirmation_url = auth_response.get("confirmation_url")
    if confirmation_url:
        await send_signup_confirm(payload.email, confirmation_url)
    if payload.intent == "provider":
        await send_provider_welcome(payload.email)

    return {
        "ok": True,
        "message": "Check your email to confirm your account.",
        "confirmation_url": confirmation_url,
    }


@router.get("/auth/confirm")
async def confirm_email(token_hash: str, type: str = "email") -> RedirectResponse:
    auth_response = await get_auth_client().verify_token_hash(token_hash, type)
    response = RedirectResponse(
        (auth_response.get("user", {}).get("user_metadata") or {}).get("post_confirm_path", "/chat"),
        status_code=303,
    )
    set_session_cookies(
        response,
        auth_response["access_token"],
        auth_response.get("refresh_token"),
    )
    return response


@router.post("/auth/login")
async def login(payload: LoginRequest, response: Response) -> dict[str, object]:
    auth_client = get_auth_client()
    if payload.magic_link:
        await auth_client.send_magic_link(payload.email)
        return {"ok": True, "message": "Check your email for a magic login link."}
    if not payload.password:
        raise HTTPException(status_code=400, detail="Password is required")

    auth_response = await auth_client.login_with_password(payload.email, payload.password)
    csrf_token = set_session_cookies(
        response,
        auth_response["access_token"],
        auth_response.get("refresh_token"),
    )
    return {"ok": True, "csrf_token": csrf_token}


@router.post("/auth/logout")
async def logout(response: Response) -> dict[str, bool]:
    clear_session_cookies(response)
    return {"ok": True}


@router.get("/me")
async def me(request: Request) -> dict[str, object]:
    user = await current_session_user(request)
    store = get_beta_store()
    profile = await store.get_profile(user.id)
    if not profile:
        profile = await store.create_profile(user.id, user.email, user.role, None)
    provider = await store.get_provider(user.id)
    return {
        "id": user.id,
        "email": user.email,
        "role": profile.get("role", user.role),
        "subscription_status": profile.get("subscription_status", "none"),
        "plan": BETA_PLAN if profile.get("subscription_status") == "active" else None,
        "trial": {
            "active": trial_is_active(profile),
            "request_count": int(profile.get("trial_request_count") or 0),
            "limit": 50,
        },
        "provider_status": provider.get("status") if provider else None,
        "provider": provider,
        "invites": await store.get_user_invites(user.id),
        "subscription_current_period_end": profile.get("subscription_current_period_end"),
    }


async def _current_profile(request: Request) -> dict:
    user = await current_session_user(request)
    profile = await get_beta_store().get_profile(user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    return profile


@router.post("/billing/create-checkout-session")
async def create_checkout_session(
    request: Request,
    _: None = Depends(require_csrf),
) -> dict[str, str]:
    profile = await _current_profile(request)
    checkout_url = await create_beta_checkout_session(profile)
    return {"url": checkout_url, "checkout_url": checkout_url}


@router.post("/billing/portal")
async def billing_portal(
    request: Request,
    _: None = Depends(require_csrf),
) -> dict[str, str]:
    profile = await _current_profile(request)
    portal_url = await create_customer_portal_session(profile)
    return {"url": portal_url}


@router.get("/billing/invoices")
async def billing_invoices(request: Request) -> dict[str, object]:
    profile = await _current_profile(request)
    return {"invoices": list_invoice_history(profile)}


@router.post("/provider/accept-terms")
async def accept_provider_terms(
    request: Request,
    _: None = Depends(require_csrf),
) -> dict[str, object]:
    user = await current_session_user(request)
    provider = await get_beta_store().accept_provider_terms(user.id, BETA_PROVIDER_TERMS_VERSION)
    await track_event("provider_claim", user.id, {"terms_version": BETA_PROVIDER_TERMS_VERSION})
    return {"ok": True, "provider": provider}


@router.post("/admin/seed-invites")
async def seed_invites(
    payload: SeedInvitesRequest,
    request: Request,
) -> dict[str, object]:
    if request.headers.get("x-admin-secret") != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid admin secret")
    invites = await get_beta_store().seed_root_invites(payload.count, payload.created_by)
    return {"invites": invites}


async def _checkout_url_for_gate(profile: dict) -> str:
    return await create_beta_checkout_session(profile)


@router.post("/chat")
async def beta_chat(
    payload: BetaChatRequest,
    request: Request,
    _: None = Depends(require_csrf),
):
    user = await current_session_user(request)
    store = get_beta_store()
    profile = await store.get_profile(user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found")

    subscribed = profile.get("subscription_status") == "active"
    over_trial = not trial_is_active(profile) or int(profile.get("trial_request_count") or 0) >= 50
    if not subscribed and over_trial:
        checkout_url = await _checkout_url_for_gate(profile)
        return JSONResponse(
            status_code=402,
            content={"message": "Subscribe to continue", "checkout_url": checkout_url},
        )

    updated_profile = await store.increment_trial_usage(user.id)
    if int(updated_profile.get("trial_request_count") or 0) == 1:
        await track_event("first_chat", user.id, {})

    chat_request = ChatRequest(
        subscriber_id=user.id,
        messages=payload.messages,
        system=payload.system,
        stream=payload.stream,
    )
    result = await run_pipeline(chat_request)
    if not payload.stream:
        return result

    async def events():
        for stage in ("classify", "cache", "prune", "compress", "route", "verify", "settle"):
            yield f"event: stage\ndata: {{\"stage\":\"{stage}\",\"status\":\"done\"}}\n\n"
        for token in result.answer.split():
            yield f"event: token\ndata: {{\"text\":\"{token} \"}}\n\n"
        yield f"event: done\ndata: {result.model_dump_json()}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")

