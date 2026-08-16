import sqlite3
import threading
from contextlib import contextmanager
from typing import Generator

from .config import get_settings

_local = threading.local()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(db_path: str | None = None) -> None:
    path = db_path or get_settings().database
    conn = get_connection(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at          TEXT    NOT NULL,
            received_at_epoch_ms INTEGER,
            station_id           TEXT,
            frequency_hz         INTEGER,
            source_icao          TEXT,
            destination_icao     TEXT,
            direction            TEXT,
            message_type         TEXT,
            aircraft_registration TEXT,
            flight_id            TEXT,
            message_text         TEXT,
            raw_json             TEXT    NOT NULL,
            inserted_at          TEXT    NOT NULL,
            message_hash         TEXT    NOT NULL UNIQUE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_received_at
            ON messages (received_at);
        CREATE INDEX IF NOT EXISTS idx_messages_source_icao
            ON messages (source_icao);
        CREATE INDEX IF NOT EXISTS idx_messages_destination_icao
            ON messages (destination_icao);
        CREATE INDEX IF NOT EXISTS idx_messages_frequency_hz
            ON messages (frequency_hz);
        CREATE INDEX IF NOT EXISTS idx_messages_inserted_at
            ON messages (inserted_at);

        CREATE TABLE IF NOT EXISTS collector_state (
            spool_path  TEXT PRIMARY KEY,
            byte_offset INTEGER NOT NULL DEFAULT 0,
            updated_at  TEXT    NOT NULL
        );
    """)
    conn.commit()


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or get_settings().database
    if not hasattr(_local, "connections"):
        _local.connections = {}
    if path not in _local.connections:
        _local.connections[path] = _connect(path)
    return _local.connections[path]


@contextmanager
def get_cursor(db_path: str | None = None) -> Generator[sqlite3.Cursor, None, None]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
