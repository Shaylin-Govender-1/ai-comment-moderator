"""Application configuration, loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings.

    Values are read from environment variables (and a local ``.env`` file if
    present). Everything except ``anthropic_api_key`` has a sensible default so
    the app is easy to run.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---
    anthropic_api_key: str = ""
    moderation_model: str = "claude-sonnet-4-6"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2

    # --- Validation limits ---
    max_comment_length: int = 10_000

    # --- Rate limiting (bonus) ---
    rate_limit_enabled: bool = True
    rate_limit: str = "10/minute"

    # --- Storage ---
    log_file: str = "moderation_log.json"

    # --- Webhook / notifications (bonus) ---
    webhook_url: str = ""

    @property
    def llm_configured(self) -> bool:
        """Whether a usable API key is present."""
        return bool(self.anthropic_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
