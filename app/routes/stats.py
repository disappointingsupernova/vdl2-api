from __future__ import annotations

from sqlalchemy import func

from fastapi import APIRouter

from app.config import get_settings
from app.database import Message, get_session
from app.schemas import StatsResponse

router = APIRouter()


@router.get("/stats", response_model=StatsResponse, summary="Aggregate message statistics")
async def stats() -> StatsResponse:
    settings = get_settings()

    with get_session(settings.database) as session:
        total = session.query(func.count(Message.id)).scalar() or 0

        last_minute = (
            session.query(func.count(Message.id))
            .filter(Message.received_at >= func.datetime("now", "-1 minutes"))
            .scalar() or 0
        )

        last_hour = (
            session.query(func.count(Message.id))
            .filter(Message.received_at >= func.datetime("now", "-1 hours"))
            .scalar() or 0
        )

        freq_rows = (
            session.query(Message.frequency_hz, func.count(Message.id).label("cnt"))
            .filter(Message.frequency_hz.isnot(None))
            .group_by(Message.frequency_hz)
            .all()
        )
        by_freq = {str(r.frequency_hz): r.cnt for r in freq_rows}

        unique_aircraft = (
            session.query(func.count(func.distinct(Message.source_icao)))
            .filter(
                Message.source_icao.isnot(None),
                Message.received_at >= func.datetime("now", "-1 hours"),
            )
            .scalar() or 0
        )

    return StatsResponse(
        messages_total=total,
        messages_last_minute=last_minute,
        messages_last_hour=last_hour,
        messages_by_frequency=by_freq,
        unique_aircraft_last_hour=unique_aircraft,
    )
