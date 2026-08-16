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
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.database import CollectorState, Message, get_session
from app.parser import parse_message

log = logging.getLogger(__name__)


def _now_iso() -> str:
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Checkpoint persistence
# ---------------------------------------------------------------------------

def load_offset(db_path: str, spool_path: str) -> int:
    with get_session(db_path) as session:
        state = session.get(CollectorState, spool_path)
    return state.byte_offset if state else 0


def save_offset(db_path: str, spool_path: str, offset: int) -> None:
    with get_session(db_path) as session:
        session.execute(
            sqlite_insert(CollectorState).values(
                spool_path=spool_path,
                byte_offset=offset,
                updated_at=_now_iso(),
            ).on_conflict_do_update(
                index_elements=["spool_path"],
                set_={"byte_offset": offset, "updated_at": _now_iso()},
            )
        )


# ---------------------------------------------------------------------------
# Single-pass drain of an open file handle
# ---------------------------------------------------------------------------

def drain(fh, db_path: str, spool_path: str) -> int:
    """Read all complete lines from fh, insert into DB, return lines inserted."""
    records: list[dict] = []
    final_offset = fh.tell()

    while True:
        raw_line = fh.readline()
        if not raw_line:
            break
        line = raw_line.strip()
        if not line:
            final_offset = fh.tell()
            continue
        record = parse_message(line)
        if record is None:
            final_offset = fh.tell()
            continue
        records.append(record)
        final_offset = fh.tell()

    if not records:
        return 0

    inserted = 0
    try:
        with get_session(db_path) as session:
            for record in records:
                stmt = sqlite_insert(Message).values(**record).prefix_with("OR IGNORE")
                result = session.execute(stmt)
                inserted += result.rowcount
    except SQLAlchemyError as exc:
        log.error("DB insert error: %s", exc)
        return inserted

    save_offset(db_path, spool_path, final_offset)
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
    _stop_after: int | None = None,
) -> None:
    settings = get_settings()
    spool = spool_path or settings.spool
    db = db_path or settings.database

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

            if fh is None:
                if not os.path.exists(spool):
                    time.sleep(poll_interval)
                    continue
                offset = load_offset(db, spool)
                try:
                    fh = open(spool, "r", encoding="utf-8", errors="replace")
                except OSError as exc:
                    log.error("Cannot open spool %s: %s — retrying", spool, exc)
                    time.sleep(poll_interval)
                    continue
                fh.seek(offset)
                current_inode = _inode(spool)
                log.info("Opened spool at offset %d (inode %s)", offset, current_inode)

            live_inode = _inode(spool)
            if live_inode is not None and live_inode != current_inode:
                log.info("Rotation detected — draining old file")
                drain(fh, db, fh.name)
                fh.close()
                fh = None
                current_inode = None
                continue

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
    cutoff = (
        datetime.now(tz=timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    with get_session(db) as session:
        deleted = (
            session.query(Message)
            .filter(Message.inserted_at < cutoff)
            .delete(synchronize_session=False)
        )
        return deleted
