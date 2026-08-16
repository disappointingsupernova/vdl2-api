"""
Collector: tails the dumpvdl2 JSONL spool and inserts records into SQLite.

Responsibilities:
- Resume from a persisted byte offset after restart.
- Detect hourly file rotation (rename + new file) and drain the old file first.
- Ignore duplicate messages via the message_hash UNIQUE constraint.
- Never crash on a bad line; log and continue.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings
from .database import get_connection, get_cursor, init_db
from .parser import parse_message

log = logging.getLogger(__name__)

_INSERT_SQL = """
    INSERT OR IGNORE INTO messages
        (received_at, received_at_epoch_ms, station_id, frequency_hz,
         source_icao, destination_icao, direction, message_type,
         aircraft_registration, flight_id, message_text, raw_json,
         inserted_at, message_hash)
    VALUES
        (:received_at, :received_at_epoch_ms, :station_id, :frequency_hz,
         :source_icao, :destination_icao, :direction, :message_type,
         :aircraft_registration, :flight_id, :message_text, :raw_json,
         :inserted_at, :message_hash)
"""


def _now_iso() -> str:
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Checkpoint persistence
# ---------------------------------------------------------------------------

def load_offset(db_path: str, spool_path: str) -> int:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT byte_offset FROM collector_state WHERE spool_path = ?",
        (spool_path,),
    ).fetchone()
    return row[0] if row else 0


def save_offset(db_path: str, spool_path: str, offset: int) -> None:
    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO collector_state (spool_path, byte_offset, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(spool_path) DO UPDATE SET
            byte_offset = excluded.byte_offset,
            updated_at  = excluded.updated_at
        """,
        (spool_path, offset, _now_iso()),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Single-pass drain of an open file handle
# ---------------------------------------------------------------------------

def drain(fh, db_path: str, spool_path: str) -> int:
    """Read all complete lines from fh, insert into DB, return lines inserted."""
    inserted = 0
    while True:
        raw_line = fh.readline()
        if not raw_line:  # EOF
            break
        line = raw_line.strip()
        if not line:
            save_offset(db_path, spool_path, fh.tell())
            continue
        record = parse_message(line)
        if record is None:
            save_offset(db_path, spool_path, fh.tell())
            continue
        try:
            with get_cursor(db_path) as cur:
                cur.execute(_INSERT_SQL, record)
                inserted += cur.rowcount
        except sqlite3.Error as exc:
            log.error("DB insert error: %s", exc)
        save_offset(db_path, spool_path, fh.tell())
    return inserted


# ---------------------------------------------------------------------------
# Rotation detection
# ---------------------------------------------------------------------------

def _inode(path: str) -> int | None:
    try:
        return os.stat(path).st_ino
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Main collector loop
# ---------------------------------------------------------------------------

def run_collector(
    spool_path: str | None = None,
    db_path: str | None = None,
    poll_interval: float = 1.0,
    *,
    _stop_after: int | None = None,  # for testing only
) -> None:
    settings = get_settings()
    spool = spool_path or settings.spool
    db = db_path or settings.database

    init_db(db)

    log.info("Collector starting — spool=%s db=%s", spool, db)

    fh = None
    current_inode: int | None = None
    iterations = 0

    try:
        while True:
            if _stop_after is not None:
                if iterations >= _stop_after:
                    break
                iterations += 1

            spool_exists = os.path.exists(spool)

            # --- open or reopen file ---
            if fh is None:
                if not spool_exists:
                    time.sleep(poll_interval)
                    continue
                offset = load_offset(db, spool)
                fh = open(spool, "r", encoding="utf-8", errors="replace")
                fh.seek(offset)
                current_inode = _inode(spool)
                log.info("Opened spool at offset %d (inode %s)", offset, current_inode)

            # --- detect rotation ---
            live_inode = _inode(spool)
            if live_inode is not None and live_inode != current_inode:
                # New file has appeared; drain remainder of old file first
                log.info("Rotation detected — draining old file")
                drain(fh, db, fh.name)
                fh.close()
                fh = None
                current_inode = None
                continue  # reopen on next iteration

            # --- drain available lines ---
            n = drain(fh, db, spool)
            if n:
                log.debug("Inserted %d message(s)", n)

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        log.info("Collector stopped")
    finally:
        if fh:
            fh.close()


# ---------------------------------------------------------------------------
# Retention cleanup
# ---------------------------------------------------------------------------

def purge_old_messages(db_path: str | None = None, retention_days: int | None = None) -> int:
    settings = get_settings()
    db = db_path or settings.database
    days = retention_days if retention_days is not None else settings.retention_days
    with get_cursor(db) as cur:
        cur.execute(
            "DELETE FROM messages WHERE inserted_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        return cur.rowcount
