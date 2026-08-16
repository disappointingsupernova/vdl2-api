from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from ..config import get_settings
from ..database import get_connection
from ..schemas import HealthResponse

router = APIRouter()

# Set by the collector background task in main.py
collector_running: bool = False


@router.get("/health", response_model=HealthResponse, summary="Service health check")
async def health() -> HealthResponse:
    settings = get_settings()

    db_status = "ok"
    total = 0
    last_msg_at = None
    age_seconds = None

    try:
        conn = get_connection(settings.database)
        total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        row = conn.execute(
            "SELECT inserted_at FROM messages ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            last_msg_at = row["inserted_at"]
            try:
                dt = datetime.fromisoformat(last_msg_at.replace("Z", "+00:00"))
                age_seconds = (datetime.now(tz=timezone.utc) - dt).total_seconds()
            except ValueError:
                pass
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        database=db_status,
        collector="ok" if collector_running else "unknown",
        last_message_at=last_msg_at,
        last_message_age_seconds=round(age_seconds, 1) if age_seconds is not None else None,
        total_messages=total,
    )
