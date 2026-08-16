import pytest
import sqlite3
import tempfile
import os

from app.database import init_db, get_connection, get_cursor


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def test_schema_created(db_path):
    conn = get_connection(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "messages" in tables
    assert "collector_state" in tables


def test_wal_mode(db_path):
    conn = get_connection(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_message_hash_unique(db_path):
    row = dict(
        received_at="2026-08-16T16:24:09.000Z",
        received_at_epoch_ms=1786897449000,
        station_id="adsb-pi",
        frequency_hz=136975000,
        source_icao="4CADF7",
        destination_icao=None,
        direction="downlink",
        message_type=None,
        aircraft_registration=None,
        flight_id=None,
        message_text=None,
        raw_json='{"t":1}',
        inserted_at="2026-08-16T16:24:09.100Z",
        message_hash="abc123",
    )
    sql = """
        INSERT INTO messages
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
    with get_cursor(db_path) as cur:
        cur.execute(sql, row)

    with pytest.raises(sqlite3.IntegrityError):
        with get_cursor(db_path) as cur:
            cur.execute(sql, row)


def test_autoincrement_id(db_path):
    sql = """
        INSERT INTO messages
            (received_at, station_id, raw_json, inserted_at, message_hash)
        VALUES (?, ?, ?, ?, ?)
    """
    with get_cursor(db_path) as cur:
        cur.execute(sql, ("2026-08-16T16:24:09Z", "s", '{}', "2026-08-16T16:24:09Z", "h1"))
        cur.execute(sql, ("2026-08-16T16:24:10Z", "s", '{}', "2026-08-16T16:24:10Z", "h2"))

    conn = get_connection(db_path)
    ids = [r[0] for r in conn.execute("SELECT id FROM messages ORDER BY id").fetchall()]
    assert ids == [1, 2]
