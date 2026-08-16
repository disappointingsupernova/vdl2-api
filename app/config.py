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

    # CORS — empty list means no cross-origin requests are permitted.
    cors_origins: List[str] = []

    # API key authentication — disabled when empty.
    # Set to a long random string to require X-API-Key on all requests.
    api_key: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> List[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v  # type: ignore[return-value]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
