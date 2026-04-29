"""Runtime configuration for the NeuralMesh Smart Orchestrator."""

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
