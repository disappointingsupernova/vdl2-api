from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VDL2_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # HTTP server
    api_host: str = "0.0.0.0"
    api_port: int = 5001

    # Paths
    database: str = "/var/lib/vdl2/vdl2.db"
    spool: str = "/var/lib/vdl2/messages.jsonl"

    # Retention
    retention_days: int = 30

    # Pagination
    default_limit: int = 500
    max_limit: int = 5000

    # CORS — empty string/list means no cross-origin requests are permitted.
    # Declared as str so pydantic-settings does not attempt to JSON-parse the
    # env var value before the validator runs. An empty VDL2_CORS_ORIGINS=""
    # would fail JSON list parsing in pydantic-settings 2.x before reaching
    # the validator. The validator converts the comma-separated string to a list.
    cors_origins: str = ""

    # API key authentication — disabled when empty.
    # Set to a long random string to require X-API-Key on all requests.
    api_key: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: object) -> object:
        # Pass through as-is; the property below does the splitting.
        # This validator exists only to normalise None to "".
        if v is None:
            return ""
        return v

    def get_cors_origins(self) -> List[str]:
        """Return cors_origins as a list, splitting on commas."""
        if not self.cors_origins:
            return []
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
