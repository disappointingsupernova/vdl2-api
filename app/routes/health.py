from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func

from fastapi import APIRouter

from app.config import get_settings
from app.database import Message, get_session
from app.schemas import HealthResponse

router = APIRouter()

collector_running: bool = False


@router.get("/health", response_model=HealthResponse, summary="Service health check")
async def health() -> HealthResponse:
    settings = get_settings()

    db_status = "ok"
    total = 0
    last_msg_at = None
    age_seconds = None

    try:
        with get_session(settings.database) as session:
            total = session.query(func.count(Message.id)).scalar() or 0
            last = (
                session.query(Message.inserted_at)
                .order_by(Message.id.desc())
                .limit(1)
                .scalar()
            )
            if last:
                last_msg_at = last
                try:
                    dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
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
