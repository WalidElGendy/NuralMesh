"""Runtime configuration for the NeuralMesh Smart Orchestrator."""

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load orchestrator settings from environment variables.

    Args:
        None.

    Returns:
        Settings object with service URLs, mock subscriber IDs, and optional API keys.

    Cost/quality target:
        Centralizes configuration so model routing and provider mocks can run with
        zero secrets while allowing real LiteLLM calls when keys are configured.
    """

    model_config = SettingsConfigDict(env_prefix="NM_", extra="ignore")

    environment: Literal["local", "test", "prod"] = "local"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    postgres_dsn: str = "postgresql://neuralmesh:neuralmesh@localhost:5432/neuralmesh"
    cache_similarity_threshold: float = 0.95
    valid_subscribers: set[str] = Field(default_factory=lambda: {"demo-sub", "sub_pro_demo", "sub_enterprise_demo"})
    enable_real_frontier_calls: bool = True


CLASSIFY_MODEL = os.getenv("CLASSIFY_MODEL", "llama-3.1-8b")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
MODEL_MAP = {
    "llama-3.1-8b": os.getenv("LLAMA_MODEL", "ollama/llama3.1:8b"),
    "mistral-7b": os.getenv("MISTRAL_MODEL", "ollama/mistral:7b"),
    "qwen-coder-7b": os.getenv("QWEN_MODEL", "ollama/qwen2.5-coder:7b"),
    "deepseek-v3": os.getenv("DEEPSEEK_MODEL", "deepseek/deepseek-chat"),
    "claude-sonnet": os.getenv("CLAUDE_MODEL", "anthropic/claude-sonnet-4-5"),
    "gemini-2.5-pro": os.getenv("GEMINI_MODEL", "gemini/gemini-2.5-pro"),
}
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.72"))
ROUTE_MODEL_PREFIX = os.getenv("ROUTE_MODEL_PREFIX", "live")
PRUNE_THRESHOLD = int(os.getenv("PRUNE_THRESHOLD", "2000"))
PRUNE_MODEL = os.getenv("PRUNE_MODEL", "mistral-7b")
PRUNE_MODEL_PREFIX = os.getenv("PRUNE_MODEL_PREFIX", "live")


@lru_cache
def get_settings() -> Settings:
    """Return cached process settings.

    Args:
        None.

    Returns:
        Settings instance.

    Cost/quality target:
        Avoid repeated environment parsing on the hot chat path.
    """

    return Settings()
