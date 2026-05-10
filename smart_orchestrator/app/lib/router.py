from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Literal

LADDERS = {
    "code":      ["qwen-coder-7b", "deepseek-v3", "claude-sonnet"],
    "creative":  ["llama-3.1-8b",  "claude-sonnet"],
    "factual":   ["llama-3.1-8b",  "gemini-2.5-pro"],
    "reasoning": ["llama-3.1-8b",  "deepseek-v3",  "claude-sonnet"],
    "math":      ["qwen-coder-7b",  "deepseek-v3",  "gemini-2.5-pro"],
    "chat":      ["llama-3.1-8b"],
}

MODEL_MAP = {
    "llama-3.1-8b":   os.getenv("LLAMA_MODEL",    "ollama/llama3.1:8b"),
    "mistral-7b":     os.getenv("MISTRAL_MODEL",   "ollama/mistral:7b"),
    "qwen-coder-7b":  os.getenv("QWEN_MODEL",      "ollama/qwen2.5-coder:7b"),
    "deepseek-v3":    os.getenv("DEEPSEEK_MODEL",  "deepseek/deepseek-chat"),
    "claude-sonnet":  os.getenv("CLAUDE_MODEL",    "anthropic/claude-sonnet-4-5"),
    "gemini-2.5-pro": os.getenv("GEMINI_MODEL",    "gemini/gemini-2.5-pro"),
}


def get_ladder(category: str) -> list:
    return LADDERS.get(category, LADDERS["chat"])


def resolve_model(alias: str) -> str:
    return MODEL_MAP.get(alias, alias)


def pick_model(category: str, tier: str, hint: str | None = None) -> tuple:
    if hint and hint in MODEL_MAP:
        return (resolve_model(hint), [])
    ladder = get_ladder(category)
    n = len(ladder)
    if tier == "ultra":
        idx = n - 1
    elif tier == "pro":
        idx = 1 if n > 1 else 0
    else:  # free
        idx = 0
    alias = ladder[idx]
    remaining = ladder[idx + 1:]
    return (resolve_model(alias), remaining)


def next_model(remaining: list) -> str | None:
    if remaining:
        return resolve_model(remaining[0])
    return None


DEFAULT_GROQ_PERCENT = 20
RouteMode = Literal["auto", "fast", "sovereign"]
RouteTarget = Literal["groq", "sovereign"]


@dataclass(frozen=True)
class RouteChoice:
    """Decision for one beta inference request."""

    route: RouteTarget
    served_by: str | None
    node_id: str | None = None
    queued: bool = False


def auto_route_groq_percent() -> int:
    """Read the runtime Groq split percentage."""

    raw_value = os.getenv("NM_AUTO_ROUTE_GROQ_PERCENT", str(DEFAULT_GROQ_PERCENT))
    try:
        return max(0, min(100, int(raw_value)))
    except ValueError:
        return DEFAULT_GROQ_PERCENT


def _normalise_mode(mode: str | None) -> RouteMode:
    if mode == "fast":
        return "fast"
    if mode == "sovereign":
        return "sovereign"
    return "auto"


def deterministic_groq_bucket(user_id: str, request_id: str) -> int:
    """Map a user/request pair to a stable bucket in [0, 99]."""

    digest = hashlib.sha256(f"{user_id}:{request_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def choose_route(
    *,
    mode: str | None,
    user_id: str,
    request_id: str,
    available_nodes: list[str] | None = None,
) -> RouteChoice:
    """Choose sovereign node or Groq for a beta inference request."""

    available_nodes = available_nodes or []
    requested_mode = _normalise_mode(mode)
    if requested_mode == "fast":
        return RouteChoice(route="groq", served_by="groq")

    if requested_mode == "auto":
        bucket = deterministic_groq_bucket(user_id, request_id)
        if bucket < auto_route_groq_percent():
            return RouteChoice(route="groq", served_by="groq")

    if available_nodes:
        node_id = sorted(available_nodes)[0]
        return RouteChoice(route="sovereign", served_by=f"node:{node_id}", node_id=node_id)

    return RouteChoice(route="sovereign", served_by=None, queued=True)
