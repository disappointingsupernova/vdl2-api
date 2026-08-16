from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import (
    Column,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.engine import Connection, Engine

from .config import get_settings

metadata = MetaData()

messages = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("received_at", Text, nullable=False),
    Column("received_at_epoch_ms", Integer),
    Column("station_id", Text),
    Column("frequency_hz", Integer),
    Column("source_icao", Text),
    Column("destination_icao", Text),
    Column("direction", Text),
    Column("message_type", Text),
    Column("aircraft_registration", Text),
    Column("flight_id", Text),
    Column("message_text", Text),
    Column("raw_json", Text, nullable=False),
    Column("inserted_at", Text, nullable=False),
    Column("message_hash", Text, nullable=False, unique=True),
    Index("idx_messages_received_at", "received_at"),
    Index("idx_messages_source_icao", "source_icao"),
    Index("idx_messages_destination_icao", "destination_icao"),
    Index("idx_messages_frequency_hz", "frequency_hz"),
    Index("idx_messages_inserted_at", "inserted_at"),
)

collector_state = Table(
    "collector_state",
    metadata,
    Column("spool_path", Text, primary_key=True),
    Column("byte_offset", Integer, nullable=False, default=0),
    Column("updated_at", Text, nullable=False),
)

_engines: dict[str, Engine] = {}


def _make_engine(db_path: str) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_pragmas(conn, _record):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")

    return engine


def get_engine(db_path: str | None = None) -> Engine:
    path = db_path or get_settings().database
    if path not in _engines:
        _engines[path] = _make_engine(path)
    return _engines[path]


def init_db(db_path: str | None = None) -> None:
    metadata.create_all(get_engine(db_path))


@contextmanager
def get_conn(db_path: str | None = None) -> Generator[Connection, None, None]:
    """Yield a transactional connection; commits on exit, rolls back on error."""
    with get_engine(db_path).begin() as conn:
        yield conn
