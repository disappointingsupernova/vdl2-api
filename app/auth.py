from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from app.config import get_settings

_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(key: str | None = Security(_header_scheme)) -> None:
    """
    FastAPI dependency — enforces API key authentication when VDL2_API_KEY is set.
    When the setting is empty, all requests are allowed through.
    """
    expected = get_settings().api_key
    if not expected:
        return  # authentication disabled
    if not key or not secrets.compare_digest(key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
