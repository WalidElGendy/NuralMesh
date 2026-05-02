import os

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
