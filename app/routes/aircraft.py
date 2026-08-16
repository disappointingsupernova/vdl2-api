from __future__ import annotations

from fastapi import APIRouter, Path, Query
from sqlalchemy import func

from app.config import get_settings
from app.database import Message, get_session
from app.models import query_messages
from app.schemas import AircraftListResponse, AircraftSummary, MessagesResponse

router = APIRouter()


@router.get(
    "/aircraft/{icao}/messages",
    response_model=MessagesResponse,
    summary="Messages for a specific aircraft",
)
async def aircraft_messages(
    icao: str = Path(description="ICAO hex address"),
    after_id: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=5000),
) -> MessagesResponse:
    settings = get_settings()
    msgs = query_messages(
        settings.database,
        after_id=after_id,
        limit=min(limit, settings.max_limit),
        icao=icao,
    )
    return MessagesResponse(
        messages=msgs,
        count=len(msgs),
        first_id=msgs[0].id if msgs else None,
        last_id=msgs[-1].id if msgs else None,
        has_more=False,
    )


@router.get("/aircraft", response_model=AircraftListResponse, summary="Aircraft observed recently")
async def list_aircraft(
    hours: int = Query(24, ge=1, le=168, description="Lookback window in hours"),
) -> AircraftListResponse:
    settings = get_settings()
    window = f"-{hours} hours"

    with get_session(settings.database) as session:
        rows = (
            session.query(
                Message.source_icao.label("icao"),
                func.min(Message.received_at).label("first_seen"),
                func.max(Message.received_at).label("last_seen"),
                func.count().label("message_count"),
                func.max(Message.aircraft_registration).label("registration"),
                func.max(Message.flight_id).label("flight_id"),
            )
            .filter(
                Message.source_icao.isnot(None),
                Message.received_at >= func.datetime("now", window),
            )
            .group_by(Message.source_icao)
            .order_by(func.max(Message.received_at).desc())
            .all()
        )

    return AircraftListResponse(
        aircraft=[
            AircraftSummary(
                icao=r.icao,
                first_seen=r.first_seen,
                last_seen=r.last_seen,
                message_count=r.message_count,
                registration=r.registration,
                flight_id=r.flight_id,
            )
            for r in rows
        ]
    )
