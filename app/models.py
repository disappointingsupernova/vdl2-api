from __future__ import annotations

import json
from typing import Literal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .database import Message, get_session
from .schemas import AddressSummary, MessageOut


def _to_schema(msg: Message) -> MessageOut:
    try:
        raw = json.loads(msg.raw_json or "{}")
    except json.JSONDecodeError:
        raw = {}

    avlc = raw.get("avlc") or {}
    src = avlc.get("src") or {}
    dst = avlc.get("dst") or {}

    return MessageOut(
        id=msg.id,
        timestamp=msg.received_at,
        timestamp_ms=msg.received_at_epoch_ms,
        ingested_at=msg.inserted_at,
        station_id=msg.station_id,
        frequency_hz=msg.frequency_hz,
        source=AddressSummary(icao=msg.source_icao, type=src.get("type")),
        destination=AddressSummary(icao=msg.destination_icao, type=dst.get("type")),
        direction=msg.direction,
        message_type=msg.message_type,
        aircraft_registration=msg.aircraft_registration,
        flight_id=msg.flight_id,
        message_text=msg.message_text,
        raw=raw,
    )


def query_messages(
    db_path: str,
    *,
    after_id: int = 0,
    limit: int = 500,
    since: str | None = None,
    until: str | None = None,
    icao: str | None = None,
    frequency: int | None = None,
    order: Literal["ASC", "DESC"] = "ASC",
) -> list[MessageOut]:
    with get_session(db_path) as session:
        q = session.query(Message).filter(Message.id > after_id)

        if since:
            q = q.filter(Message.received_at >= since)
        if until:
            q = q.filter(Message.received_at <= until)
        if icao:
            upper = icao.upper()
            q = q.filter(or_(Message.source_icao == upper, Message.destination_icao == upper))
        if frequency:
            q = q.filter(Message.frequency_hz == frequency)

        q = q.order_by(Message.id.asc() if order == "ASC" else Message.id.desc())
        rows = q.limit(limit).all()

    return [_to_schema(m) for m in rows]
