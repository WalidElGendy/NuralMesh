"""Conversation endpoints — v0.4 (streaming, telemetry, no personas).

Wired into the FastAPI app via `from agents import router` + `app.include_router(router)` in api.py.

CHANGES FROM v0.3
-----------------
* Personas removed. `resolve_persona()` picked a system prompt by substring-
  matching the conversation *title*, and `list_agents()` seeded every user with
  seven threads named "Design Agent", "Sales Agent" and so on. The result was
  that a thread's title silently dictated the assistant's behaviour for every
  question in it. See mesh_prompts.py for the full account.
* Streaming. v0.3 called SiliconFlow with `stream: False`, so a reply appeared
  as one block after a long silence. `/turn/stream` emits SSE.
* Telemetry. v0.3 stored `served_by` NULL and `tokens`/`latency_ms` 0 on every
  message row, making the inference network invisible in its own product.
* `/complete` — a stateless completion used by the client's reasoning pipeline
  (route, plan, verify) without polluting the conversation history.
* History is trimmed to a character budget instead of a flat 50 messages.
"""

import json
import logging
import os
import time
import urllib.request as _urlreq
import urllib.error as _urlerr
from datetime import UTC, datetime
from typing import Any, Iterator

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api import get_supabase_client  # reuse the same Supabase client factory
import mesh_router
from mesh_prompts import (
    DEFAULT_MODE,
    MODES,
    PLANNER,
    ROUTER,
    TITLER,
    VERIFIER,
    build_system,
    mode_config,
)


router = APIRouter(prefix="/api/agents", tags=["agents"])
logger = logging.getLogger(__name__)

# ---------------- Conversation defaults ----------------
#
# v0.3 kept a NAMED_AGENTS list here and auto-seeded seven persona threads for
# every user, then read the persona back off the thread title. Both are gone.
# A conversation is a conversation; behaviour comes from the mode the user
# picks on the composer, not from what the thread happens to be called.

DEFAULT_TITLE = "New thread"

# Conversations are never seeded. Set NM_SEED_NAMED_AGENTS=1 only if some other
# client still depends on the old seven rows existing.
SEED_NAMED_AGENTS = os.environ.get("NM_SEED_NAMED_AGENTS", "").strip() == "1"
LEGACY_NAMED_AGENTS = [
    "Design Agent",
    "Content Agent",
    "Cowork Agent",
    "Email Agent",
    "Sales Agent",
    "Marketing Agent",
    "Personal Assistant Agent",
]


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
    # v0.4: the answer mode is chosen on the composer, not inferred from the
    # thread title. `context` carries client-side retrieval (recalled passages,
    # web sources, the plan) so the server can ground the prompt without
    # owning the search stack.
    mode: str = Field(default="ask")
    context: dict | None = None


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
        # No auto-seeding. v0.3 created seven persona-named threads on first
        # load, which is where the persona bug entered: the thread title then
        # decided how every answer in it was written. A new user now starts
        # with an empty list and one composer.
        if SEED_NAMED_AGENTS:
            existing_titles = {(r.get("title") or "").strip() for r in rows}
            missing = [t for t in LEGACY_NAMED_AGENTS if t not in existing_titles]
            if missing:
                try:
                    supabase.table("conversations").insert(
                        [{"user_id": user_id, "title": t} for t in missing]
                    ).execute()
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


# NOTE: literal paths must be declared before "/{agent_id}", because
# FastAPI matches routes in declaration order — otherwise GET /_modes is
# captured by get_agent() with agent_id="_modes".
# ---------------- Stateless completion for the reasoning pipeline ----------
class CompleteRequest(BaseModel):
    task: str = Field(..., pattern="^(route|plan|verify|title|free)$")
    content: str = Field(..., min_length=1, max_length=24000)
    draft: str | None = Field(None, max_length=24000)
    sources: list[dict] | None = None


class CompleteResponse(BaseModel):
    task: str
    result: Any
    meta: dict


@router.post("/complete", response_model=CompleteResponse)
def complete(body: CompleteRequest, user_id: str = Depends(get_current_user_id)):
    """Run one pipeline step without writing to a conversation.

    The client's pipeline (route -> recall -> plan/ground -> draft -> verify)
    needs completions that are not turns. Keeping them here means the prompts
    stay server-side and never reach the browser.
    """
    if body.task == "route":
        text, meta = _chat(
            [{"role": "system", "content": ROUTER}, {"role": "user", "content": body.content[:2000]}],
            model=FAST_MODEL, temperature=0.0, max_tokens=200, json_mode=True,
        )
        return CompleteResponse(task=body.task, result=_parse_json(text, {}), meta=meta)

    if body.task == "plan":
        text, meta = _chat(
            [{"role": "system", "content": PLANNER}, {"role": "user", "content": body.content}],
            temperature=0.2, max_tokens=500, json_mode=True,
        )
        return CompleteResponse(task=body.task, result=_parse_json(text, None), meta=meta)

    if body.task == "verify":
        ctx = (
            "\n\nSUPPLIED CONTEXT:\n"
            + "\n".join(
                f"[{s.get('n', i + 1)}] {s.get('title')} — {str(s.get('snippet', ''))[:300]}"
                for i, s in enumerate(body.sources or [])
            )
            if body.sources
            else "\n\n(No sources supplied — treat every specific figure as unsupported.)"
        )
        text, meta = _chat(
            [
                {"role": "system", "content": VERIFIER},
                {
                    "role": "user",
                    "content": f"QUESTION:\n{body.content}\n\nDRAFT:\n{(body.draft or '')[:8000]}{ctx}",
                },
            ],
            temperature=0.0, max_tokens=700, json_mode=True,
        )
        return CompleteResponse(
            task=body.task,
            result=_parse_json(text, {"ok": True, "issues": [], "confidence": None}),
            meta=meta,
        )

    if body.task == "title":
        return CompleteResponse(
            task=body.task, result=_auto_title(body.content), meta={"model": FAST_MODEL}
        )

    text, meta = _chat(
        [{"role": "user", "content": body.content}], temperature=0.4, max_tokens=1200
    )
    return CompleteResponse(task=body.task, result=text, meta=meta)


# ---------------- Modes (so the client never hardcodes them) ----------------
@router.get("/_modes")
def list_modes():
    return {
        "default": DEFAULT_MODE,
        "modes": [
            {"id": k, "label": v["label"], "temperature": v["temperature"]}
            for k, v in MODES.items()
        ],
    }


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


# ---------------- LLM layer ----------------
#
# One upstream, two shapes: buffered and streamed. Both return telemetry, so a
# message row can finally record which model answered, how many tokens it cost
# and how long it took. v0.3 stored NULL / 0 / 0 for all three.

UPSTREAM_URL = os.environ.get(
    "NM_UPSTREAM_URL", "https://api.siliconflow.com/v1/chat/completions"
)
UPSTREAM_KEY_ENV = "SILICONFLOW_API_KEY"
DEFAULT_MODEL = os.environ.get("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3.1")
FAST_MODEL = os.environ.get("NM_FAST_MODEL", DEFAULT_MODEL)

# Upper bound on history sent upstream. v0.3 sent a flat 50 messages, which on
# a long analytical thread is tens of thousands of tokens of mostly stale text.
HISTORY_CHAR_BUDGET = int(os.environ.get("NM_HISTORY_CHARS", "24000"))


def _upstream_key() -> str:
    key = os.environ.get(UPSTREAM_KEY_ENV)
    if not key:
        raise HTTPException(status_code=503, detail="chat_not_configured")
    return key


def _request(payload: dict, stream: bool):
    req = _urlreq.Request(
        UPSTREAM_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_upstream_key()}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        },
        method="POST",
    )
    try:
        return _urlreq.urlopen(req, timeout=180 if stream else 90)
    except _urlerr.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="ignore")[:300]
        except Exception:
            pass
        logger.error("upstream_http_error status=%s body=%s", e.code, body_text)
        raise HTTPException(status_code=502, detail=f"upstream_error_{e.code}")
    except Exception as e:
        logger.exception("upstream_request_failed")
        raise HTTPException(status_code=502, detail=f"upstream_error: {e}")


def _chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 2048,
    json_mode: bool = False,
) -> tuple[str, dict]:
    """Buffered completion. Returns (text, telemetry)."""
    payload: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    t0 = time.perf_counter()
    with _request(payload, stream=False) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        logger.error("upstream_bad_response data=%s", str(data)[:300])
        raise HTTPException(status_code=502, detail="upstream_bad_response")

    usage = data.get("usage") or {}
    meta = {
        "model": payload["model"],
        "served_by": data.get("served_by") or _provider_label(),
        "tokens": int(usage.get("completion_tokens") or _estimate_tokens(text)),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "latency_ms": elapsed_ms,
    }
    return text, meta


def _chat_stream(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 2048,
) -> Iterator[tuple[str, str, dict]]:
    """Streamed completion.

    Yields ("delta", chunk, {}) for each token and finally ("done", full, meta).
    """
    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }

    t0 = time.perf_counter()
    ttft_ms: int | None = None
    parts: list[str] = []
    tokens = 0

    with _request(payload, stream=True) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line or not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            try:
                frame = json.loads(body)
            except Exception:
                continue
            choices = frame.get("choices") or []
            if choices:
                delta = (choices[0].get("delta") or {}).get("content") or ""
                if delta:
                    if ttft_ms is None:
                        ttft_ms = int((time.perf_counter() - t0) * 1000)
                    parts.append(delta)
                    yield ("delta", delta, {})
            usage = frame.get("usage") or {}
            if usage.get("completion_tokens"):
                tokens = int(usage["completion_tokens"])

    full = "".join(parts)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    meta = {
        "model": payload["model"],
        "served_by": _provider_label(),
        "tokens": tokens or _estimate_tokens(full),
        "latency_ms": elapsed_ms,
        "ttft_ms": ttft_ms,
    }
    yield ("done", full, meta)


def _route_and_stream(
    supabase,
    messages: list[dict],
    *,
    temperature: float,
    max_tokens: int,
    user_id: str | None = None,
    conversation_id: str | None = None,
) -> Iterator[tuple[str, str, dict]]:
    """Offer the turn to the mesh first, buy it only if the mesh cannot take it.

    The mesh is given `NM_DISPATCH_DEADLINE_S` to claim the job. If nothing
    claims it, the job is abandoned and we fall through to the paid provider —
    before a single token has been emitted, so the user sees a slightly later
    first token rather than a stall or an error.

    Every outcome is written to routing_events with a reason code, which is
    what makes `select * from fallback_reasons_7d` a provider-recruitment
    backlog rather than a guess.
    """
    decision = mesh_router.decide(supabase)

    if decision.target == "mesh":
        job_id = None
        try:
            job_id = mesh_router.enqueue(
                supabase,
                messages=messages,
                model=decision.model,
                params={"temperature": temperature, "max_tokens": max_tokens, "stream": True},
                user_id=user_id,
                conversation_id=conversation_id,
            )
            for kind, payload, meta in mesh_router.stream_job(supabase, job_id):
                if kind == "done":
                    mesh_router.record(
                        supabase, target="mesh", tokens=meta.get("tokens", 0),
                        user_id=user_id, job_id=job_id, node_id=meta.get("node_id"),
                        model=meta.get("model"), latency_ms=meta.get("latency_ms"),
                        ttft_ms=meta.get("ttft_ms"),
                    )
                yield (kind, payload, meta)
            return
        except mesh_router.MeshUnavailable as e:
            logger.info("mesh_unavailable reason=%s — falling back", e.reason)
            decision = mesh_router.Decision("fallback", e.reason)
        except Exception:
            logger.exception("mesh_dispatch_failed — falling back")
            decision = mesh_router.Decision("fallback", "node_error")

    # Paid path. Recorded as a fallback WITH its reason, so the cost of not
    # being sovereign is a number rather than an impression.
    for kind, payload, meta in _chat_stream(
        messages, temperature=temperature, max_tokens=max_tokens
    ):
        if kind == "done":
            meta = {**meta, "sovereign": False, "fallback_reason": decision.reason}
            mesh_router.record(
                supabase, target="fallback", tokens=meta.get("tokens", 0),
                user_id=user_id, model=meta.get("model"), reason=decision.reason,
                latency_ms=meta.get("latency_ms"), ttft_ms=meta.get("ttft_ms"),
            )
        yield (kind, payload, meta)


def _provider_label() -> str:
    """Where the tokens actually came from.

    The beta markets 'Llama 3.3 70B on the sovereign GPU mesh' while this
    endpoint calls SiliconFlow. Record the truth on the row rather than
    implying mesh provenance that did not happen.
    """
    host = UPSTREAM_URL.split("/")[2] if "//" in UPSTREAM_URL else UPSTREAM_URL
    return os.environ.get("NM_PROVIDER_LABEL") or host


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _parse_json(text: str, fallback=None):
    """Models wrap JSON in prose or a fence often enough to be worth handling."""
    if not text:
        return fallback
    body = text
    if "```" in body:
        chunks = body.split("```")
        for c in chunks:
            c = c.strip()
            if c.startswith("json"):
                c = c[4:].strip()
            if c.startswith("{"):
                body = c
                break
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end < 0:
        return fallback
    try:
        return json.loads(body[start : end + 1])
    except Exception:
        return fallback


def _trim_history(history: list[dict], budget: int = HISTORY_CHAR_BUDGET) -> list[dict]:
    """Keep the most recent turns that fit the budget, oldest first."""
    kept: list[dict] = []
    used = 0
    for m in reversed(history):
        c = m.get("content") or ""
        if used + len(c) > budget and kept:
            break
        kept.append(m)
        used += len(c)
    return list(reversed(kept))


def _auto_title(first_user_message: str) -> str:
    try:
        title, _ = _chat(
            [
                {"role": "system", "content": TITLER},
                {"role": "user", "content": first_user_message[:500]},
            ],
            model=FAST_MODEL,
            temperature=0.3,
            max_tokens=24,
        )
        title = title.strip().strip('"').strip("'").rstrip(".")
        return title[:60]
    except Exception:
        logger.warning("auto_title_failed", exc_info=True)
        return ""


# ---------------- Turn plumbing ----------------


def _load_history(supabase, agent_id: str) -> list[dict]:
    try:
        hist = (
            supabase.table("messages")
            .select("role,content")
            .eq("conversation_id", agent_id)
            .order("created_at", desc=False)
            .limit(200)
            .execute()
        )
    except Exception as e:
        logger.exception("load_history_failed")
        raise HTTPException(status_code=500, detail=f"load_history_failed: {e}")
    return _trim_history(
        [
            {"role": m["role"], "content": m["content"]}
            for m in (hist.data or [])
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
    )


def _set_status(supabase, agent_id: str, status: str, **extra) -> None:
    """Update conversation state.

    v0.3 wrapped this in a bare `except Exception: logger.exception(...)`, and
    because the columns did not exist yet, every call failed silently — which
    is why no beta conversation has ever had updated_at move off created_at.
    Migration 026 adds the columns; this logs loudly enough to notice if they
    go missing again.
    """
    payload = {"status": status, **{k: v for k, v in extra.items() if v is not None}}
    try:
        supabase.table("conversations").update(payload).eq("id", agent_id).execute()
    except Exception:
        logger.warning(
            "conversation_state_update_failed id=%s payload=%s "
            "(is migration 026 applied?)",
            agent_id,
            list(payload),
            exc_info=True,
        )


def _insert_message(supabase, agent_id: str, role: str, content: str,
                    meta: dict | None = None, mode: str | None = None):
    row: dict[str, Any] = {
        "conversation_id": agent_id,
        "role": role,
        "content": content,
    }
    if meta:
        row["served_by"] = meta.get("served_by")
        row["tokens"] = int(meta.get("tokens") or 0)
        row["latency_ms"] = int(meta.get("latency_ms") or 0)
    if mode:
        row["mode"] = mode
    if meta:
        row["meta"] = meta

    try:
        ins = supabase.table("messages").insert(row).execute()
    except Exception:
        # Retry without the v0.4 columns so a missing migration degrades to the
        # v0.3 behaviour instead of losing the user's message entirely.
        logger.warning("insert_message_full_failed, retrying minimal", exc_info=True)
        minimal = {"conversation_id": agent_id, "role": role, "content": content}
        try:
            ins = supabase.table("messages").insert(minimal).execute()
        except Exception as e:
            logger.exception("insert_message_failed")
            raise HTTPException(status_code=500, detail=f"insert_message_failed: {e}")
    if not ins.data:
        raise HTTPException(status_code=500, detail="insert_message_empty")
    return ins.data[0]


def _build_messages(conv, history, content, mode, context):
    """Assemble the upstream message list for one turn."""
    ctx = context or {}
    sources = ctx.get("sources") or []
    memory = ctx.get("memory") or []
    plan = ctx.get("plan")

    system = build_system(
        mode,
        grounded=bool(sources),
        quantitative=bool(ctx.get("quantitative")) or mode == "analyze",
        has_memory=bool(memory),
    )

    blocks = []
    if memory:
        blocks.append(
            "WORKSPACE MEMORY\n"
            + "\n".join(f"- {str(m)[:600]}" for m in memory[:8])
        )
    if plan and plan.get("steps"):
        blocks.append(
            "YOUR PLAN (follow it, do not restate it)\n"
            + "\n".join(
                f"{i + 1}. {s.get('q')} — needs: {s.get('needs')}"
                for i, s in enumerate(plan["steps"])
            )
        )
    if sources:
        blocks.append(
            "RETRIEVED SOURCES\n"
            + "\n\n".join(
                f"[{s.get('n', i + 1)}] {s.get('title')} ({s.get('site', '')})\n"
                f"{s.get('url', '')}\n{str(s.get('snippet', ''))[:700]}"
                for i, s in enumerate(sources[:8])
            )
        )

    user_content = ("\n\n".join(blocks) + "\n\n---\n\n" + content) if blocks else content
    return [{"role": "system", "content": system}] + history + [
        {"role": "user", "content": user_content}
    ]


# ---------------- Turn (buffered, back-compatible) ----------------
@router.post("/{agent_id}/turn", response_model=AgentTurnResponse)
def agent_turn(
    agent_id: str,
    body: AgentTurnRequest,
    user_id: str = Depends(get_current_user_id),
):
    supabase = get_supabase_client()
    conv = _load_conv(supabase, agent_id, user_id)
    mode = body.mode if body.mode in MODES else DEFAULT_MODE
    cfg = mode_config(mode)

    _insert_message(supabase, agent_id, "user", body.content, mode=mode)
    _set_status(supabase, agent_id, "running", last_preview=body.content[:120])

    history = _load_history(supabase, agent_id)[:-1] or []
    messages = _build_messages(conv, history, body.content, mode, body.context)

    try:
        parts, meta = [], {}
        for kind, payload, m in _route_and_stream(
            supabase, messages,
            temperature=cfg["temperature"], max_tokens=cfg["max_tokens"],
            user_id=user_id, conversation_id=agent_id,
        ):
            if kind == "delta":
                parts.append(payload)
            else:
                meta = m
        answer = "".join(parts)
    except HTTPException:
        _set_status(supabase, agent_id, "error")
        raise

    asst_row = _insert_message(supabase, agent_id, "assistant", answer, meta=meta, mode=mode)

    title = conv.get("title")
    if not title or title in ("New chat", "Untitled", DEFAULT_TITLE):
        auto = _auto_title(body.content)
        if auto:
            title = auto
            # Isolated from the status write: a failure here must not also lose
            # the status update, which is exactly how v0.3 lost every title.
            try:
                supabase.table("conversations").update({"title": auto}).eq(
                    "id", agent_id
                ).execute()
                conv["title"] = auto
            except Exception:
                logger.warning("title_update_failed id=%s", agent_id, exc_info=True)

    _set_status(supabase, agent_id, "idle", last_preview=answer[:120], mode=mode)
    latest = {**conv, "status": "idle", "last_preview": answer[:120]}

    return AgentTurnResponse(
        assistant_message=AgentMessageOut(
            id=str(asst_row["id"]),
            role="assistant",
            content=answer,
            created_at=asst_row["created_at"],
        ),
        agent=_row_to_agent_summary(latest),
    )


# ---------------- Turn (streamed) ----------------
@router.post("/{agent_id}/turn/stream")
def agent_turn_stream(
    agent_id: str,
    body: AgentTurnRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Server-sent events.

    Frames:
      data: {"type":"start","mode":"analyze"}
      data: {"type":"delta","v":"…"}
      data: {"type":"done","message_id":"…","meta":{…},"agent":{…}}
      data: {"type":"error","detail":"…"}
      data: [DONE]
    """
    supabase = get_supabase_client()
    conv = _load_conv(supabase, agent_id, user_id)
    mode = body.mode if body.mode in MODES else DEFAULT_MODE
    cfg = mode_config(mode)

    _insert_message(supabase, agent_id, "user", body.content, mode=mode)
    _set_status(supabase, agent_id, "running", last_preview=body.content[:120])

    history = _load_history(supabase, agent_id)[:-1] or []
    messages = _build_messages(conv, history, body.content, mode, body.context)

    def events() -> Iterator[str]:
        def frame(obj) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        yield frame({"type": "start", "mode": mode, "model": DEFAULT_MODEL})
        answer, meta = "", {}
        try:
            for kind, payload, m in _route_and_stream(
                supabase, messages,
                temperature=cfg["temperature"],
                max_tokens=cfg["max_tokens"],
                user_id=user_id,
                conversation_id=agent_id,
            ):
                if kind == "delta":
                    yield frame({"type": "delta", "v": payload})
                else:
                    answer, meta = payload, m
        except HTTPException as e:
            _set_status(supabase, agent_id, "error")
            yield frame({"type": "error", "detail": str(e.detail)})
            yield "data: [DONE]\n\n"
            return
        except Exception as e:
            logger.exception("stream_failed")
            _set_status(supabase, agent_id, "error")
            yield frame({"type": "error", "detail": f"stream_failed: {e}"})
            yield "data: [DONE]\n\n"
            return

        try:
            asst_row = _insert_message(
                supabase, agent_id, "assistant", answer, meta=meta, mode=mode
            )
        except HTTPException as e:
            yield frame({"type": "error", "detail": str(e.detail)})
            yield "data: [DONE]\n\n"
            return

        title = conv.get("title")
        if not title or title in ("New chat", "Untitled", DEFAULT_TITLE):
            auto = _auto_title(body.content)
            if auto:
                try:
                    supabase.table("conversations").update({"title": auto}).eq(
                        "id", agent_id
                    ).execute()
                    conv["title"] = auto
                except Exception:
                    logger.warning("title_update_failed id=%s", agent_id, exc_info=True)

        _set_status(supabase, agent_id, "idle", last_preview=answer[:120], mode=mode)
        latest = {**conv, "status": "idle", "last_preview": answer[:120]}

        yield frame(
            {
                "type": "done",
                "message_id": str(asst_row["id"]),
                "created_at": asst_row["created_at"],
                "meta": meta,
                "agent": json.loads(_row_to_agent_summary(latest).model_dump_json()),
            }
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",   # nginx must not buffer an SSE body
            "Connection": "keep-alive",
        },
    )
