"""
Parse raw dumpvdl2 JSON objects into a flat dict ready for database insertion.

dumpvdl2 produces many protocol variants; most fields are optional.
We never discard a message because an optional field is absent.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def _utc_iso(ts: Any) -> str | None:
    """Return a UTC ISO-8601 string from a Unix timestamp (int/float) or None."""
    if ts is None:
        return None
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    except (TypeError, ValueError, OSError):
        return None


def _epoch_ms(ts: Any) -> int | None:
    if ts is None:
        return None
    try:
        return int(float(ts) * 1000)
    except (TypeError, ValueError):
        return None


def _icao(addr: Any) -> str | None:
    if addr is None:
        return None
    try:
        return str(addr).upper()
    except Exception:
        return None


def _extract_station(obj: dict) -> str | None:
    return obj.get("station_id") or obj.get("station") or None


def _extract_frequency(obj: dict) -> int | None:
    freq = obj.get("freq") or obj.get("frequency")
    if freq is None:
        return None
    try:
        return int(freq)
    except (TypeError, ValueError):
        return None


def _extract_addresses(obj: dict) -> tuple[str | None, str | None, str | None]:
    """Return (source_icao, destination_icao, direction)."""
    avlc = obj.get("avlc") or {}
    src = avlc.get("src") or {}
    dst = avlc.get("dst") or {}

    src_addr = _icao(src.get("addr"))
    dst_addr = _icao(dst.get("addr"))

    # direction: aircraft→ground = downlink, ground→aircraft = uplink
    src_type = src.get("type", "")
    if src_type == "Aircraft":
        direction = "downlink"
    elif src_type in ("Ground station", "Ground_station"):
        direction = "uplink"
    else:
        direction = None

    return src_addr, dst_addr, direction


def _extract_acars(obj: dict) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (message_type, registration, flight_id, message_text)."""
    avlc = obj.get("avlc") or {}
    acars = None

    # Walk common nesting paths
    for path in [
        ["acars"],
        ["x25", "acars"],
        ["clnp", "acars"],
        ["idrp", "acars"],
    ]:
        node = avlc
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, dict):
            acars = node
            break

    if acars is None:
        return None, None, None, None

    msg_type = acars.get("label")
    reg = acars.get("reg")
    flight = acars.get("flight")
    text = acars.get("msg_text") or acars.get("text")

    return (
        str(msg_type).strip() if msg_type else None,
        str(reg).strip() if reg else None,
        str(flight).strip() if flight else None,
        str(text).strip() if text else None,
    )


def _make_hash(raw_json: str) -> str:
    return hashlib.sha256(raw_json.encode()).hexdigest()


def parse_message(raw_json: str) -> dict | None:
    """
    Parse one line of dumpvdl2 JSON output.

    Returns a dict ready for database insertion, or None if the line cannot
    be parsed at all.  Logs failures but never raises.
    """
    try:
        obj: dict = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        log.warning("JSON parse error: %s — line: %.120s", exc, raw_json)
        return None

    if not isinstance(obj, dict):
        log.warning("Unexpected JSON type %s — line: %.120s", type(obj).__name__, raw_json)
        return None

    try:
        ts = obj.get("t")
        received_at = _utc_iso(ts)
        if received_at is None:
            # Fall back to current time so the record is still stored
            now = datetime.now(tz=timezone.utc)
            received_at = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
            log.debug("Missing timestamp in message; using ingestion time")

        src_icao, dst_icao, direction = _extract_addresses(obj)
        msg_type, reg, flight, text = _extract_acars(obj)

        now_utc = datetime.now(tz=timezone.utc)
        inserted_at = now_utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now_utc.microsecond // 1000:03d}Z"

        return {
            "received_at": received_at,
            "received_at_epoch_ms": _epoch_ms(ts),
            "station_id": _extract_station(obj),
            "frequency_hz": _extract_frequency(obj),
            "source_icao": src_icao,
            "destination_icao": dst_icao,
            "direction": direction,
            "message_type": msg_type,
            "aircraft_registration": reg,
            "flight_id": flight,
            "message_text": text,
            "raw_json": raw_json.strip(),
            "inserted_at": inserted_at,
            "message_hash": _make_hash(raw_json.strip()),
        }
    except Exception as exc:
        log.exception("Unexpected error parsing message: %s — line: %.120s", exc, raw_json)
        return None
