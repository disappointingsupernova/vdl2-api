import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import init_db, get_engine, get_conn


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def test_schema_created(db_path):
    with get_engine(db_path).connect() as conn:
        tables = {r[0] for r in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()}
    assert "messages" in tables
    assert "collector_state" in tables


def test_wal_mode(db_path):
    with get_engine(db_path).connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
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
    sql = text("""
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
    """)
    with get_conn(db_path) as conn:
        conn.execute(sql, row)

    with pytest.raises(IntegrityError):
        with get_conn(db_path) as conn:
            conn.execute(sql, row)


def test_autoincrement_id(db_path):
    sql = text("""
        INSERT INTO messages (received_at, station_id, raw_json, inserted_at, message_hash)
        VALUES (:ra, :s, :r, :ia, :h)
    """)
    with get_conn(db_path) as conn:
        conn.execute(sql, {"ra": "2026-08-16T16:24:09Z", "s": "s", "r": "{}", "ia": "2026-08-16T16:24:09Z", "h": "h1"})
        conn.execute(sql, {"ra": "2026-08-16T16:24:10Z", "s": "s", "r": "{}", "ia": "2026-08-16T16:24:10Z", "h": "h2"})

    with get_engine(db_path).connect() as conn:
        ids = [r[0] for r in conn.execute(text("SELECT id FROM messages ORDER BY id")).fetchall()]
    assert ids == [1, 2]
