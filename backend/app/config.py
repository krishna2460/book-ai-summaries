"""
Centralized application configuration.

All settings are loaded from environment variables (or a .env file) using
pydantic-settings.  Every module imports `settings` from here — there are
no hardcoded connection strings or API keys anywhere else.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated settings with defaults where safe."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",          # don't blow up on unknown env vars
    )

    # ── Database ──────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://booksumm:booksumm_secret@localhost:5432/booksumm"
    database_url_sync: str = "postgresql+psycopg2://booksumm:booksumm_secret@localhost:5432/booksumm"

    # ── AIMLAPI (OpenAI-compatible) ──────────────────────
    aiml_api_key: str = ""
    aiml_base_url: str = "https://api.aimlapi.com/v1"
    aiml_chat_model: str = "gpt-4o-mini"
    aiml_embedding_model: str = "text-embedding-3-small"

    # ── Groq (OpenAI-compatible chat API) ────────────────
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_chat_model: str = "allam-2-7b"

    # ── Google Gemini (OpenAI-compatible API) ────────────
    gemini_api_key: str = ""
    gemini_api_keys: str = ""  # comma-separated keys from separate projects
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_chat_model: str = "gemini-3.6-flash"
    gemini_embedding_model: str = "gemini-embedding-001"

    # ── Auth ──────────────────────────────────────────────
    jwt_secret_key: str = "change-me-to-a-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440        # 24 h

    # ── Langfuse ──────────────────────────────────────────
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # ── App ───────────────────────────────────────────────
    upload_dir: str = "./uploads"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton so env is read only once."""
    return Settings()


settings = get_settings()
