from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.config import get_settings
from app.models import query_messages
from app.schemas import MessagesResponse

router = APIRouter()


@router.get("/messages", response_model=MessagesResponse, summary="List messages by cursor")
async def list_messages(
    after_id: int = Query(0, ge=0, description="Return messages with id > this value"),
    limit: int = Query(500, ge=1, le=5000),
    since: Optional[str] = Query(None, description="ISO 8601 UTC lower bound on received_at"),
    until: Optional[str] = Query(None, description="ISO 8601 UTC upper bound on received_at"),
    icao: Optional[str] = Query(None, description="Filter by source or destination ICAO"),
    frequency: Optional[int] = Query(None, description="Filter by frequency in Hz"),
) -> MessagesResponse:
    settings = get_settings()
    effective_limit = min(limit, settings.max_limit)
    fetch_limit = effective_limit + 1  # fetch one extra to detect has_more

    msgs = query_messages(
        settings.database,
        after_id=after_id,
        limit=fetch_limit,
        since=since,
        until=until,
        icao=icao,
        frequency=frequency,
    )

    has_more = len(msgs) > effective_limit
    msgs = msgs[:effective_limit]

    return MessagesResponse(
        messages=msgs,
        count=len(msgs),
        first_id=msgs[0].id if msgs else None,
        last_id=msgs[-1].id if msgs else None,
        has_more=has_more,
    )


@router.get("/messages/latest", response_model=MessagesResponse, summary="Return the newest N messages")
async def latest_messages(
    limit: int = Query(100, ge=1, le=5000),
) -> MessagesResponse:
    settings = get_settings()
    effective_limit = min(limit, settings.max_limit)

    msgs = query_messages(
        settings.database,
        after_id=0,
        limit=effective_limit,
        order="DESC",
    )

    return MessagesResponse(
        messages=msgs,
        count=len(msgs),
        first_id=msgs[-1].id if msgs else None,
        last_id=msgs[0].id if msgs else None,
        has_more=False,
    )
