"""Web grounding proxy — POST /api/search.

Research mode needs live facts, and the browser must never hold a search API
key. This normalises Brave, Tavily and Serper into one result shape, picks
whichever key is configured, and caches hot queries in-process.

Configure exactly one of:
    BRAVE_API_KEY    recommended — cheap, fast, returns result ages
    TAVILY_API_KEY   returns cleaned page content rather than snippets
    SERPER_API_KEY

With none configured the endpoint returns an empty result set and the client
answers from model knowledge, saying so. Grounding failing must degrade an
answer, never break a turn.

Wire into api.py:
    from mesh_search import router as _search_router
    app.include_router(_search_router)
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error as _urlerr
import urllib.parse as _urlparse
import urllib.request as _urlreq

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agents import get_current_user_id

router = APIRouter(prefix="/api", tags=["search"])
logger = logging.getLogger(__name__)

CACHE_TTL_S = 600
_cache: dict[str, tuple[float, list[dict]]] = {}


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=2, max_length=400)
    count: int = Field(default=6, ge=1, le=10)
    freshness: str | None = None       # brave: pd | pw | pm | py


class SearchResponse(BaseModel):
    results: list[dict]
    provider: str
    cached: bool = False
    error: str | None = None


def _get(url: str, headers: dict, timeout: int = 12):
    req = _urlreq.Request(url, headers=headers, method="GET")
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(url: str, headers: dict, payload: dict, timeout: int = 20):
    req = _urlreq.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _host(url: str) -> str:
    try:
        return _urlparse.urlparse(url).hostname.removeprefix("www.")
    except Exception:
        return ""


def _brave(q: str, count: int, freshness: str | None) -> list[dict]:
    params = {"q": q, "count": count}
    if freshness:
        params["freshness"] = freshness
    url = "https://api.search.brave.com/res/v1/web/search?" + _urlparse.urlencode(params)
    data = _get(url, {
        "Accept": "application/json",
        "X-Subscription-Token": os.environ["BRAVE_API_KEY"],
    })
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": _strip_tags(r.get("description", "")),
            "age": r.get("age") or r.get("page_age"),
        }
        for r in (data.get("web", {}).get("results") or [])
    ]


def _tavily(q: str, count: int) -> list[dict]:
    data = _post("https://api.tavily.com/search", {}, {
        "api_key": os.environ["TAVILY_API_KEY"],
        "query": q,
        "max_results": count,
        "search_depth": "advanced",
        "include_answer": False,
    })
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": (r.get("content") or "")[:900],
            "age": r.get("published_date"),
        }
        for r in (data.get("results") or [])
    ]


def _serper(q: str, count: int) -> list[dict]:
    data = _post(
        "https://google.serper.dev/search",
        {"X-API-KEY": os.environ["SERPER_API_KEY"]},
        {"q": q, "num": count},
    )
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("link", ""),
            "snippet": r.get("snippet", ""),
            "age": r.get("date"),
        }
        for r in (data.get("organic") or [])
    ]


def _strip_tags(s: str) -> str:
    out, depth = [], 0
    for ch in s:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, user_id: str = Depends(get_current_user_id)):
    key = f"{body.q}::{body.count}::{body.freshness or ''}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return SearchResponse(results=hit[1], provider="cache", cached=True)

    if os.environ.get("BRAVE_API_KEY"):
        provider, fn = "brave", lambda: _brave(body.q, body.count, body.freshness)
    elif os.environ.get("TAVILY_API_KEY"):
        provider, fn = "tavily", lambda: _tavily(body.q, body.count)
    elif os.environ.get("SERPER_API_KEY"):
        provider, fn = "serper", lambda: _serper(body.q, body.count)
    else:
        return SearchResponse(results=[], provider="none",
                              error="no_search_provider_configured")

    try:
        results = fn()
    except _urlerr.HTTPError as e:
        logger.warning("search_upstream_error provider=%s status=%s", provider, e.code)
        return SearchResponse(results=[], provider=provider, error=f"upstream_{e.code}")
    except Exception as e:
        logger.exception("search_failed provider=%s", provider)
        return SearchResponse(results=[], provider=provider, error=str(e)[:120])

    seen, clean = set(), []
    for r in results:
        if not r.get("url") or not r.get("title") or r["url"] in seen:
            continue
        seen.add(r["url"])
        r["site"] = _host(r["url"])
        r["n"] = len(clean) + 1
        clean.append(r)
        if len(clean) >= body.count:
            break

    _cache[key] = (time.time(), clean)
    if len(_cache) > 500:
        _cache.pop(next(iter(_cache)))

    return SearchResponse(results=clean, provider=provider)
