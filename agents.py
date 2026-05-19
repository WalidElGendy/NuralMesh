"""Multi-agent (conversations) endpoints — v0.3 (robust + agent personas).

Wired into the FastAPI app via `from agents import router` + `app.include_router(router)` in api.py.
"""

import json
import logging
import os
import urllib.request as _urlreq
import urllib.error as _urlerr
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from api import get_supabase_client  # reuse the same Supabase client factory


router = APIRouter(prefix="/api/agents", tags=["agents"])
logger = logging.getLogger(__name__)

# ---------------- Canonical seeded agent set ----------------
NAMED_AGENTS = [
    "Design Agent",
    "Content Agent",
    "Cowork Agent",
    "Email Agent",
    "Sales Agent",
    "Marketing Agent",
    "Personal Assistant Agent",
]



# ---------------- Agent persona system prompts ----------------
AGENT_PERSONAS = {
    "design": (
        "You are Design Agent — a senior product / UI / UX / visual designer for NeuralMesh. "
        "You help with wireframes, design systems, color palettes, typography, layout, accessibility, "
        "Figma workflows, and turning ideas into concrete design specs. Be specific, give concrete "
        "values (hex codes, font sizes, spacing scales), and structure complex answers with short sections."
    ),
    "content": (
        "You are Content Agent — a senior content strategist and copywriter. You produce blog posts, "
        "landing-page copy, social posts, scripts, outlines and SEO drafts. You always ask for the target "
        "audience and goal if it's unclear, then deliver in the requested tone. Provide multiple variants "
        "when useful (short / medium / long)."
    ),
    "cowork": (
        "You are Cowork Agent — a collaboration and project-operations partner. You help with meeting "
        "agendas, async standup notes, decision logs, RACI charts, retro structures, and turning chat "
        "threads into actionable tasks. Be crisp and action-oriented."
    ),
    "email": (
        "You are Email Agent — a professional email assistant. You draft, summarize, and reply to emails "
        "in the requested tone (formal, friendly, firm, apologetic, etc.). Always produce a subject line "
        "and a body. Keep emails short by default and offer a longer version on request."
    ),
    "sales": (
        "You are Sales Agent — a B2B/B2C sales co-pilot. You write cold outreach, follow-ups, discovery "
        "questions, objection-handling scripts, and proposal sections. You always tie the message to "
        "buyer pain and a clear next step (CTA). Provide concise variants (email / LinkedIn / SMS)."
    ),
    "marketing": (
        "You are Marketing Agent — a full-funnel growth marketer. You help with positioning, ICPs, "
        "campaign briefs, ad copy (Google / Meta / X / LinkedIn), landing-page hero copy, A/B test ideas, "
        "and KPI plans. Be data-aware: mention which metric a recommendation moves."
    ),
    "personal assistant": (
        "You are Personal Assistant Agent — a calm, organized executive assistant. You help plan days, "
        "summarize documents, draft quick replies, set reminders (as text), build checklists, and turn "
        "vague intents into a concrete next action. Default to being concise."
    ),
}

DEFAULT_PERSONA = (
    "You are a helpful NeuralMesh AI assistant. Be concise, accurate and helpful. "
    "If you don't know something, say so."
)


def resolve_persona(title):
    t = (title or "").strip().lower()
    if not t:
        return DEFAULT_PERSONA
    for key, prompt in AGENT_PERSONAS.items():
        if key in t:
            return prompt
    return DEFAULT_PERSONA


# ---------------- Auth ----------------
def get_current_user_id(authorization: str | None = Header(None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        supabase = get_supabase_client()
        user_resp = supabase.auth.get_user(token)
        user = getattr(user_resp, "user", None)
        user_id = getattr(user, "id", None)
        if not user_id:
            raise HTTPException(status_code=401, detail="invalid_token")
        return str(user_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_current_user_failed")
        raise HTTPException(status_code=401, detail="invalid_token")


# ---------------- Models ----------------
class AgentSummary(BaseModel):
    id: str
    title: str | None = None
    status: str
    last_preview: str | None = None
    updated_at: str
    unread_count: int = 0
    pinned: bool = False


class AgentListResponse(BaseModel):
    agents: list[AgentSummary]


class AgentCreateRequest(BaseModel):
    title: str | None = None


class AgentPatchRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    mark_read: bool | None = None


class AgentMessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


class AgentDetailResponse(BaseModel):
    agent: AgentSummary
    messages: list[AgentMessageOut]


class AgentMessagesResponse(BaseModel):
    messages: list[AgentMessageOut]


class AgentTurnRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000)


class AgentTurnResponse(BaseModel):
    assistant_message: AgentMessageOut
    agent: AgentSummary


def _row_to_agent_summary(row):
    return AgentSummary(
        id=str(row["id"]),
        title=row.get("title"),
        status=row.get("status", "idle"),
        last_preview=row.get("last_preview"),
        updated_at=row["updated_at"],
        unread_count=row.get("unread_count", 0) or 0,
        pinned=bool(row.get("pinned", False)),
    )


# ---------------- CRUD ----------------
@router.get("", response_model=AgentListResponse)
def list_agents(user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase_client()
    try:
        res = (
            supabase.table("conversations")
            .select("*")
            .eq("user_id", user_id)
            .is_("deleted_at", "null")
            .order("updated_at", desc=True)
            .limit(200)
            .execute()
        )
        rows = res.data or []
        # Auto-seed: ensure this user has a row for each canonical NAMED_AGENT
        existing_titles = {(r.get("title") or "").strip() for r in rows}
        missing = [t for t in NAMED_AGENTS if t not in existing_titles]
        if missing:
            try:
                payload = [{"user_id": user_id, "title": t} for t in missing]
                supabase.table("conversations").insert(payload).execute()
                # Re-fetch so the response includes the freshly seeded rows
                res = (
                    supabase.table("conversations")
                    .select("*")
                    .eq("user_id", user_id)
                    .is_("deleted_at", "null")
                    .order("updated_at", desc=True)
                    .limit(200)
                    .execute()
                )
                rows = res.data or []
            except Exception:
                logger.exception("seed_named_agents_failed")
    except Exception as e:
        logger.exception("list_agents_failed")
        raise HTTPException(status_code=500, detail=f"list_agents_failed: {e}")
    return AgentListResponse(agents=[_row_to_agent_summary(r) for r in rows])


@router.post("", response_model=AgentSummary)
def create_agent(body: AgentCreateRequest, user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase_client()
    try:
        res = (
            supabase.table("conversations")
            .insert({"user_id": user_id, "title": body.title})
            .execute()
        )
    except Exception as e:
        logger.exception("create_agent_failed")
        raise HTTPException(status_code=500, detail=f"create_agent_failed: {e}")
    if not res.data:
        raise HTTPException(status_code=500, detail="agent_create_failed")
    return _row_to_agent_summary(res.data[0])


def _load_conv(supabase, agent_id, user_id):
    try:
        conv = (
            supabase.table("conversations")
            .select("*")
            .eq("id", agent_id)
            .eq("user_id", user_id)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.exception("load_conv_failed")
        raise HTTPException(status_code=500, detail=f"load_conv_failed: {e}")
    if not conv.data:
        raise HTTPException(status_code=404, detail="agent_not_found")
    return conv.data[0]


@router.get("/{agent_id}", response_model=AgentDetailResponse)
def get_agent(agent_id: str, user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase_client()
    conv_row = _load_conv(supabase, agent_id, user_id)
    try:
        msgs = (
            supabase.table("messages")
            .select("*")
            .eq("conversation_id", agent_id)
            .order("created_at", desc=False)
            .limit(1000)
            .execute()
        )
    except Exception as e:
        logger.exception("load_messages_failed")
        raise HTTPException(status_code=500, detail=f"load_messages_failed: {e}")
    messages = [
        AgentMessageOut(
            id=str(m["id"]),
            role=m["role"],
            content=m["content"],
            created_at=m["created_at"],
        )
        for m in (msgs.data or [])
    ]
    return AgentDetailResponse(agent=_row_to_agent_summary(conv_row), messages=messages)


@router.get("/{agent_id}/messages", response_model=AgentMessagesResponse)
def get_agent_messages(agent_id: str, user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase_client()
    _load_conv(supabase, agent_id, user_id)
    try:
        msgs = (
            supabase.table("messages")
            .select("*")
            .eq("conversation_id", agent_id)
            .order("created_at", desc=False)
            .limit(1000)
            .execute()
        )
    except Exception as e:
        logger.exception("load_messages_failed")
        raise HTTPException(status_code=500, detail=f"load_messages_failed: {e}")
    messages = [
        AgentMessageOut(
            id=str(m["id"]),
            role=m["role"],
            content=m["content"],
            created_at=m["created_at"],
        )
        for m in (msgs.data or [])
    ]
    return AgentMessagesResponse(messages=messages)


@router.patch("/{agent_id}", response_model=AgentSummary)
def patch_agent(agent_id: str, body: AgentPatchRequest, user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase_client()
    update = {}
    if body.title is not None:
        update["title"] = body.title
    if body.pinned is not None:
        update["pinned"] = body.pinned
    if body.mark_read:
        update["unread_count"] = 0
    if not update:
        raise HTTPException(status_code=400, detail="no_fields")
    try:
        res = (
            supabase.table("conversations")
            .update(update)
            .eq("id", agent_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as e:
        logger.exception("patch_agent_failed")
        raise HTTPException(status_code=500, detail=f"patch_agent_failed: {e}")
    if not res.data:
        raise HTTPException(status_code=404, detail="agent_not_found")
    return _row_to_agent_summary(res.data[0])


@router.delete("/{agent_id}")
def delete_agent(agent_id: str, user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase_client()
    try:
        res = (
            supabase.table("conversations")
            .update({"deleted_at": datetime.now(UTC).isoformat()})
            .eq("id", agent_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as e:
        logger.exception("delete_agent_failed")
        raise HTTPException(status_code=500, detail=f"delete_agent_failed: {e}")
    if not res.data:
        raise HTTPException(status_code=404, detail="agent_not_found")
    return {"ok": True}


# ---------------- LLM helper ----------------
def _siliconflow_chat(messages):
    sf_key = os.environ.get("SILICONFLOW_API_KEY")
    model = os.environ.get("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3.1")
    if not sf_key:
        raise HTTPException(status_code=503, detail="chat_not_configured")
    payload = json.dumps(
        {"model": model, "messages": messages, "stream": False}
    ).encode("utf-8")
    req = _urlreq.Request(
        "https://api.siliconflow.com/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {sf_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlreq.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except _urlerr.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="ignore")[:300]
        except Exception:
            pass
        logger.error("siliconflow_http_error status=%s body=%s", e.code, body_text)
        raise HTTPException(status_code=502, detail=f"upstream_error_{e.code}")
    except Exception as e:
        logger.exception("siliconflow_request_failed")
        raise HTTPException(status_code=502, detail=f"upstream_error: {e}")
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        logger.error("siliconflow_bad_response data=%s", str(data)[:300])
        raise HTTPException(status_code=502, detail="upstream_bad_response")


def _auto_title(first_user_message):
    try:
        title = _siliconflow_chat([
            {"role": "system", "content": "Return a 2-5 word title for this chat. No quotes, no punctuation at the end."},
            {"role": "user", "content": first_user_message[:500]},
        ]).strip().strip('"').strip("'")
        return title[:60] if title else ""
    except Exception:
        return ""


# ---------------- Turn ----------------
@router.post("/{agent_id}/turn", response_model=AgentTurnResponse)
def agent_turn(agent_id: str, body: AgentTurnRequest, user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase_client()
    conv = _load_conv(supabase, agent_id, user_id)

    try:
        supabase.table("messages").insert({
            "conversation_id": agent_id,
            "role": "user",
            "content": body.content,
        }).execute()
    except Exception as e:
        logger.exception("insert_user_message_failed")
        raise HTTPException(status_code=500, detail=f"insert_user_message_failed: {e}")

    try:
        supabase.table("conversations").update({
            "status": "running",
            "last_preview": body.content[:60],
        }).eq("id", agent_id).execute()
    except Exception:
        logger.exception("conv_mark_running_failed")

    try:
        hist = (
            supabase.table("messages")
            .select("role,content")
            .eq("conversation_id", agent_id)
            .order("created_at", desc=False)
            .limit(50)
            .execute()
        )
        history = [{"role": m["role"], "content": m["content"]} for m in (hist.data or [])]
    except Exception as e:
        logger.exception("load_history_failed")
        raise HTTPException(status_code=500, detail=f"load_history_failed: {e}")

    persona = resolve_persona(conv.get("title"))
    messages_for_llm = [{"role": "system", "content": persona}] + history

    try:
        answer = _siliconflow_chat(messages_for_llm)
    except HTTPException:
        try:
            supabase.table("conversations").update({"status": "error"}).eq("id", agent_id).execute()
        except Exception:
            logger.exception("conv_mark_error_failed")
        raise

    try:
        ins = supabase.table("messages").insert({
            "conversation_id": agent_id,
            "role": "assistant",
            "content": answer,
        }).execute()
    except Exception as e:
        logger.exception("insert_assistant_message_failed")
        raise HTTPException(status_code=500, detail=f"insert_assistant_message_failed: {e}")
    if not ins.data:
        raise HTTPException(status_code=500, detail="insert_assistant_message_empty")
    asst_row = ins.data[0]

    title_update = {"status": "idle", "last_preview": answer[:60]}
    if not conv.get("title"):
        auto = _auto_title(body.content)
        if auto:
            title_update["title"] = auto
    try:
        upd = (
            supabase.table("conversations")
            .update(title_update)
            .eq("id", agent_id)
            .execute()
        )
        latest_conv = upd.data[0] if upd.data else conv
    except Exception:
        logger.exception("conv_finalize_failed")
        latest_conv = conv

    return AgentTurnResponse(
        assistant_message=AgentMessageOut(
            id=str(asst_row["id"]),
            role="assistant",
            content=answer,
            created_at=asst_row["created_at"],
        ),
        agent=_row_to_agent_summary(latest_conv),
    )
