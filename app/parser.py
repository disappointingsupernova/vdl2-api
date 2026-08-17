"""
Parse raw dumpvdl2 JSON objects into a flat dict ready for database insertion.

dumpvdl2 2.x wraps all fields under a top-level "vdl2" key:
  { "vdl2": { "freq": ..., "t": {"sec": ..., "usec": ...}, "station": ..., "avlc": { ... } } }

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


def _utc_iso(sec: Any, usec: Any = 0) -> str | None:
    """Return a UTC ISO-8601 string from sec + usec, or None."""
    if sec is None:
        return None
    try:
        ts = float(sec) + float(usec or 0) / 1_000_000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    except (TypeError, ValueError, OSError):
        return None


def _epoch_ms(sec: Any, usec: Any = 0) -> int | None:
    if sec is None:
        return None
    try:
        return int((float(sec) + float(usec or 0) / 1_000_000) * 1000)
    except (TypeError, ValueError):
        return None


def _icao(addr: Any) -> str | None:
    if addr is None:
        return None
    return str(addr).upper()


def _extract_station(vdl2: dict) -> str | None:
    return vdl2.get("station") or vdl2.get("station_id") or None


def _extract_frequency(vdl2: dict) -> int | None:
    freq = vdl2.get("freq") or vdl2.get("frequency")
    if freq is None:
        return None
    try:
        return int(freq)
    except (TypeError, ValueError):
        return None


def _extract_addresses(avlc: dict) -> tuple[str | None, str | None, str | None]:
    """Return (source_icao, destination_icao, direction)."""
    src = avlc.get("src") or {}
    dst = avlc.get("dst") or {}

    src_addr = _icao(src.get("addr"))
    dst_addr = _icao(dst.get("addr"))

    src_type = src.get("type", "")
    if src_type == "Aircraft":
        direction = "downlink"
    elif src_type in ("Ground station", "Ground_station"):
        direction = "uplink"
    else:
        direction = None

    return src_addr, dst_addr, direction


def _extract_acars(avlc: dict) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (message_type, registration, flight_id, message_text)."""
    acars = None

    # Walk common nesting paths — based on dumpvdl2 2.7.0 output structure
    for path in (
        ("acars",),
        ("x25", "acars"),
        ("x25", "clnp", "cotp", "acars"),
        ("clnp", "acars"),
        ("idrp", "acars"),
    ):
        node = avlc
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, dict):
            acars = node
            break

    if acars is not None:
        msg_type = acars.get("label")
        reg = acars.get("reg")
        flight = acars.get("flight")
        raw_text = acars.get("msg_text") or acars.get("text")
        text = str(raw_text).strip() if raw_text else None
        # Empty string after strip (e.g. Q0 ACK) should be stored as null
        text = text or None

        # Strip leading dot from registration (e.g. ".G-EZRT" → "G-EZRT")
        reg_clean = str(reg).lstrip(".").strip() if reg else None

        return (
            str(msg_type).strip() if msg_type else None,
            reg_clean or None,
            str(flight).strip() if flight else None,
            text,
        )

    # CPDLC via x25 → clnp → cotp → cpdlc
    cpdlc = None
    for path in (
        ("x25", "clnp", "cotp", "cpdlc"),
        ("x25", "clnp", "cotp", "pdu_list"),
    ):
        node = avlc
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, dict):
            cpdlc = node
            break

    if cpdlc is not None:
        text = _extract_cpdlc_text(cpdlc)
        return "_d", None, None, text

    return None, None, None, None


def _extract_cpdlc_text(cpdlc: dict) -> str | None:
    """Extract the first message text from an atc_uplink_msg or atc_downlink_msg."""
    for key in ("atc_uplink_msg", "atc_downlink_msg"):
        msg = cpdlc.get(key)
        if not isinstance(msg, dict):
            continue
        for elem in msg.get("msg_elem", []):
            text = elem.get("msg_text")
            if text:
                return str(text).strip()
    return None


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
        # dumpvdl2 2.x wraps everything under a "vdl2" key
        vdl2 = obj.get("vdl2") or {}

        t = vdl2.get("t") or {}
        sec = t.get("sec") if isinstance(t, dict) else t
        usec = t.get("usec") if isinstance(t, dict) else 0

        received_at = _utc_iso(sec, usec)
        if received_at is None:
            now = datetime.now(tz=timezone.utc)
            received_at = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
            log.debug("Missing timestamp in message; using ingestion time")

        avlc = vdl2.get("avlc") or {}
        src_icao, dst_icao, direction = _extract_addresses(avlc)
        msg_type, reg, flight, text = _extract_acars(avlc)

        now_utc = datetime.now(tz=timezone.utc)
        inserted_at = now_utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now_utc.microsecond // 1000:03d}Z"

        return {
            "received_at": received_at,
            "received_at_epoch_ms": _epoch_ms(sec, usec),
            "station_id": _extract_station(vdl2),
            "frequency_hz": _extract_frequency(vdl2),
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
