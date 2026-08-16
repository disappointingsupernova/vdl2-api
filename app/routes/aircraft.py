from __future__ import annotations

from fastapi import APIRouter, Path, Query

from ..config import get_settings
from ..database import get_connection
from ..models import query_messages
from ..schemas import AircraftListResponse, AircraftSummary, MessagesResponse

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
    conn = get_connection(settings.database)
    rows = conn.execute(
        """
        SELECT
            source_icao                          AS icao,
            MIN(received_at)                     AS first_seen,
            MAX(received_at)                     AS last_seen,
            COUNT(*)                             AS message_count,
            MAX(aircraft_registration)           AS registration,
            MAX(flight_id)                       AS flight_id
        FROM messages
        WHERE source_icao IS NOT NULL
          AND received_at >= datetime('now', :window)
        GROUP BY source_icao
        ORDER BY last_seen DESC
        """,
        {"window": f"-{hours} hours"},
    ).fetchall()

    return AircraftListResponse(
        aircraft=[
            AircraftSummary(
                icao=r["icao"],
                first_seen=r["first_seen"],
                last_seen=r["last_seen"],
                message_count=r["message_count"],
                registration=r["registration"],
                flight_id=r["flight_id"],
            )
            for r in rows
        ]
    )
