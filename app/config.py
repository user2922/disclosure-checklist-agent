"""Application settings, validated once at startup.

This module is the only place in the codebase permitted to read the environment.
Everything else calls get_settings(). A missing REQUIRED variable raises here,
at import time, rather than surfacing as a confusing failure deep in a request.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment configuration. See .env.example for the buckets."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # REQUIRED
    GEMINI_MODEL: str = Field(min_length=1)
    APP_URL: str = Field(min_length=1)
    AUDIT_LOG_PATH: str = Field(default="./audit.jsonl", min_length=1)

    # FEATURE — unset means offline mode, which is a supported mode, not an error.
    GOOGLE_API_KEY: str | None = None

    # OPTIONAL
    RATE_LIMIT_PER_MINUTE: int = Field(default=10, ge=1)
    MAX_MODEL_CALLS_PER_DAY: int = Field(default=200, ge=1)

    @field_validator("APP_URL")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        """Normalise so the Origin comparison in /api/confirm is exact."""
        return v.rstrip("/")

    @property
    def mode(self) -> Literal["live", "offline"]:
        """Whether a model will be called at all. Displayed to the user."""
        return "live" if self.GOOGLE_API_KEY else "offline"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the validated settings singleton.

    Raises pydantic.ValidationError naming the offending variable if a REQUIRED
    value is missing or malformed.
    """
    return Settings()
