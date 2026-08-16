from __future__ import annotations

from fastapi import APIRouter

from sqlalchemy import text

from ..config import get_settings
from ..database import get_engine
from ..schemas import StatsResponse

router = APIRouter()


@router.get("/stats", response_model=StatsResponse, summary="Aggregate message statistics")
async def stats() -> StatsResponse:
    settings = get_settings()
    with get_engine(settings.database).connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM messages")).scalar()

        last_minute = conn.execute(
            text("SELECT COUNT(*) FROM messages WHERE received_at >= datetime('now', '-1 minute')")
        ).scalar()

        last_hour = conn.execute(
            text("SELECT COUNT(*) FROM messages WHERE received_at >= datetime('now', '-1 hour')")
        ).scalar()

        freq_rows = conn.execute(text("""
            SELECT frequency_hz, COUNT(*) AS cnt
            FROM messages
            WHERE frequency_hz IS NOT NULL
            GROUP BY frequency_hz
        """)).mappings().all()
        by_freq = {str(r["frequency_hz"]): r["cnt"] for r in freq_rows}

        unique_aircraft = conn.execute(text("""
            SELECT COUNT(DISTINCT source_icao) FROM messages
            WHERE source_icao IS NOT NULL
              AND received_at >= datetime('now', '-1 hour')
        """)).scalar()

    return StatsResponse(
        messages_total=total,
        messages_last_minute=last_minute,
        messages_last_hour=last_hour,
        messages_by_frequency=by_freq,
        unique_aircraft_last_hour=unique_aircraft,
    )
