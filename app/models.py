"""
Shared database query helpers used by API routes.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from .database import get_connection
from .schemas import AddressSummary, MessageOut


def _row_to_message(row: sqlite3.Row) -> MessageOut:
    raw_json = row["raw_json"] or "{}"
    try:
        raw = json.loads(raw_json)
    except json.JSONDecodeError:
        raw = {}

    avlc = raw.get("avlc") or {}
    src = avlc.get("src") or {}
    dst = avlc.get("dst") or {}

    return MessageOut(
        id=row["id"],
        timestamp=row["received_at"],
        timestamp_ms=row["received_at_epoch_ms"],
        ingested_at=row["inserted_at"],
        station_id=row["station_id"],
        frequency_hz=row["frequency_hz"],
        source=AddressSummary(icao=row["source_icao"], type=src.get("type")),
        destination=AddressSummary(icao=row["destination_icao"], type=dst.get("type")),
        direction=row["direction"],
        message_type=row["message_type"],
        aircraft_registration=row["aircraft_registration"],
        flight_id=row["flight_id"],
        message_text=row["message_text"],
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
    order: str = "ASC",
) -> list[MessageOut]:
    conn = get_connection(db_path)
    clauses = ["id > :after_id"]
    params: dict[str, Any] = {"after_id": after_id, "limit": limit}

    if since:
        clauses.append("received_at >= :since")
        params["since"] = since
    if until:
        clauses.append("received_at <= :until")
        params["until"] = until
    if icao:
        clauses.append("(source_icao = :icao OR destination_icao = :icao)")
        params["icao"] = icao.upper()
    if frequency:
        clauses.append("frequency_hz = :frequency")
        params["frequency"] = frequency

    where = " AND ".join(clauses)
    sql = f"SELECT * FROM messages WHERE {where} ORDER BY id {order} LIMIT :limit"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_message(r) for r in rows]
