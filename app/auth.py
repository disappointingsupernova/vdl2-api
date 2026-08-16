from __future__ import annotations

import secrets
import logging

from fastapi import HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from app.config import get_settings

log = logging.getLogger(__name__)

_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(key: str | None = Security(_header_scheme)) -> None:
    """
    FastAPI dependency — enforces API key authentication when VDL2_API_KEY is set.
    When the setting is empty, all requests are allowed through.
    """
    expected = get_settings().api_key
    if not expected:
        return  # authentication disabled
    if not key:
        log.warning("Rejected request — X-API-Key header missing")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if not secrets.compare_digest(key, expected):
        log.warning("Rejected request — invalid X-API-Key provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
