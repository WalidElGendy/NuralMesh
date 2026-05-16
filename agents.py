"""Multi-agent (conversations) endpoints — v0.1 (non-streaming).

Wired into the FastAPI app via `from agents import router` + `app.include_router(router)`
in api.py.
"""
import json
import logging
import os
import urllib.request as _urlreq
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from api import get_supabase_client  # reuse the same Supabase client factory

router = APIRouter(prefix="/api/agents", tags=["agents"])
logger = logging.getLogger(__name__)


def get_current_user_id(authorization: str | None = Header(None)) -> str:
    """Resolve the Supabase user from a Bearer token. Returns user_id (str)."""
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


class AgentTurnRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000)


def _row_to_agent_summary(row: dict) -> AgentSummary:
    return AgentSummary(
        id=str(row["id"]),
        title=row.get("title"),
        status=row.get("status", "idle"),
        last_preview=row.get("last_preview"),
        updated_at=row["updated_at"],
        unread_count=row.get("unread_count", 0) or 0,
        pinned=bool(row.get("pinned", False)),
    )


@router.get("", response_model=AgentListResponse)
def list_agents(user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase_client()
    res = (
        supabase.table("conversations")
        .select("*")
        .eq("user_id", user_id)
        .is_("deleted_at", "null")
        .order("updated_at", desc=True)
        .limit(200)
        .execute()
    )
    return AgentListResponse(agents=[_row_to_agent_summary(r) for r in (res.data or [])])


@router.post("", response_model=AgentSummary)
def create_agent(body: AgentCreateRequest, user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase_client()
    res = (
        supabase.table("conversations")
        .insert({"user_id": user_id, "title": body.title})
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="agent_create_failed")
    return _row_to_agent_summary(res.data[0])


@router.get("/{agent_id}", response_model=AgentDetailResponse)
def get_agent(agent_id: str, user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase_client()
    conv = (
        supabase.table("conversations")
        .select("*")
        .eq("id", agent_id)
        .eq("user_id", user_id)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    )
    if not conv.data:
        raise HTTPException(status_code=404, detail="agent_not_found")
    msgs = (
        supabase.table("messages")
        .select("*")
        .eq("conversation_id", agent_id)
        .order("created_at", desc=False)
        .limit(1000)
        .execute()
    )
    messages = [
        AgentMessageOut(
            id=str(m["id"]),
            role=m["role"],
            content=m["content"],
            created_at=m["created_at"],
        )
        for m in (msgs.data or [])
    ]
    return AgentDetailResponse(agent=_row_to_agent_summary(conv.data[0]), messages=messages)


@router.patch("/{agent_id}", response_model=AgentSummary)
def patch_agent(
    agent_id: str,
    body: AgentPatchRequest,
    user_id: str = Depends(get_current_user_id),
):
    supabase = get_supabase_client()
    update: dict[str, Any] = {}
    if body.title is not None:
        update["title"] = body.title
    if body.pinned is not None:
        update["pinned"] = body.pinned
    if body.mark_read:
        update["unread_count"] = 0
    if not update:
        raise HTTPException(status_code=400, detail="no_fields")
    res = (
        supabase.table("conversations")
        .update(update)
        .eq("id", agent_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="agent_not_found")
    return _row_to_agent_summary(res.data[0])


@router.delete("/{agent_id}")
def delete_agent(agent_id: str, user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase_client()
    res = (
        supabase.table("conversations")
        .update({"deleted_at": datetime.now(UTC).isoformat()})
        .eq("id", agent_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="agent_not_found")
    return {"ok": True}


def _siliconflow_chat(messages: list[dict]) -> str:
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
    except Exception:
        logger.exception("siliconflow_request_failed")
        raise HTTPException(status_code=502, detail="upstream_error")
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        raise HTTPException(status_code=502, detail="upstream_bad_response")


def _auto_title(first_user_message: str) -> str:
    try:
        title = _siliconflow_chat([
            {"role": "system", "content": "Return a 2-5 word title for this chat. No quotes, no punctuation at the end."},
            {"role": "user", "content": first_user_message[:500]},
        ]).strip().strip('"').strip("'")
        return title[:60] if title else "Untitled agent"
    except Exception:
        return "Untitled agent"


@router.post("/{agent_id}/turn", response_model=AgentMessageOut)
def agent_turn(
    agent_id: str,
    body: AgentTurnRequest,
    user_id: str = Depends(get_current_user_id),
):
    supabase = get_supabase_client()
    conv_res = (
        supabase.table("conversations")
        .select("*")
        .eq("id", agent_id)
        .eq("user_id", user_id)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    )
    if not conv_res.data:
        raise HTTPException(status_code=404, detail="agent_not_found")
    conv = conv_res.data[0]

    supabase.table("messages").insert({
        "conversation_id": agent_id, "role": "user", "content": body.content,
    }).execute()
    supabase.table("conversations").update({
        "status": "running", "last_preview": body.content[:60],
    }).eq("id", agent_id).execute()

    hist = (
        supabase.table("messages")
        .select("role,content")
        .eq("conversation_id", agent_id)
        .order("created_at", desc=False)
        .limit(50)
        .execute()
    )
    history = [{"role": m["role"], "content": m["content"]} for m in (hist.data or [])]

    try:
        answer = _siliconflow_chat(history)
    except HTTPException:
        supabase.table("conversations").update({"status": "error"}).eq("id", agent_id).execute()
        raise

    ins = supabase.table("messages").insert({
        "conversation_id": agent_id, "role": "assistant", "content": answer,
    }).execute()
    asst_row = ins.data[0]

    title_update: dict[str, Any] = {
        "status": "idle",
        "last_preview": answer[:60],
    }
    if not conv.get("title"):
        title_update["title"] = _auto_title(body.content)
    supabase.table("conversations").update(title_update).eq("id", agent_id).execute()

    return AgentMessageOut(
        id=str(asst_row["id"]),
        role="assistant",
        content=answer,
        created_at=asst_row["created_at"],
    )
