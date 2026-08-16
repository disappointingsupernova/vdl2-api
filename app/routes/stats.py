from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..database import get_connection
from ..schemas import StatsResponse

router = APIRouter()


@router.get("/stats", response_model=StatsResponse, summary="Aggregate message statistics")
async def stats() -> StatsResponse:
    settings = get_settings()
    conn = get_connection(settings.database)

    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    last_minute = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE received_at >= datetime('now', '-1 minute')"
    ).fetchone()[0]

    last_hour = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE received_at >= datetime('now', '-1 hour')"
    ).fetchone()[0]

    freq_rows = conn.execute(
        """
        SELECT frequency_hz, COUNT(*) AS cnt
        FROM messages
        WHERE frequency_hz IS NOT NULL
        GROUP BY frequency_hz
        """
    ).fetchall()
    by_freq = {str(r["frequency_hz"]): r["cnt"] for r in freq_rows}

    unique_aircraft = conn.execute(
        """
        SELECT COUNT(DISTINCT source_icao) FROM messages
        WHERE source_icao IS NOT NULL
          AND received_at >= datetime('now', '-1 hour')
        """
    ).fetchone()[0]

    return StatsResponse(
        messages_total=total,
        messages_last_minute=last_minute,
        messages_last_hour=last_hour,
        messages_by_frequency=by_freq,
        unique_aircraft_last_hour=unique_aircraft,
    )
