import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.database import Base, CollectorState, Message, get_session, init_db, _get_factory


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def test_schema_created(db_path):
    engine = _get_factory(db_path).kw["bind"]
    table_names = inspect(engine).get_table_names()
    assert "messages" in table_names
    assert "collector_state" in table_names


def test_wal_mode(db_path):
    engine = _get_factory(db_path).kw["bind"]
    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert mode == "wal"


def test_message_hash_unique(db_path):
    msg = dict(
        received_at="2026-08-16T16:24:09.000Z",
        received_at_epoch_ms=1786897449000,
        station_id="adsb-pi",
        frequency_hz=136975000,
        source_icao="4CADF7",
        raw_json='{"t":1}',
        inserted_at="2026-08-16T16:24:09.100Z",
        message_hash="abc123",
    )
    with get_session(db_path) as session:
        session.add(Message(**msg))

    with pytest.raises(IntegrityError):
        with get_session(db_path) as session:
            session.add(Message(**msg))


def test_autoincrement_id(db_path):
    with get_session(db_path) as session:
        session.add(Message(received_at="2026-08-16T16:24:09Z", raw_json="{}", inserted_at="2026-08-16T16:24:09Z", message_hash="h1"))
        session.add(Message(received_at="2026-08-16T16:24:10Z", raw_json="{}", inserted_at="2026-08-16T16:24:10Z", message_hash="h2"))

    with get_session(db_path) as session:
        ids = [m.id for m in session.query(Message).order_by(Message.id).all()]
    assert ids == [1, 2]
