from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import Index, Integer, String, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("message_hash", name="uq_messages_hash"),
        Index("idx_messages_received_at", "received_at"),
        Index("idx_messages_source_icao", "source_icao"),
        Index("idx_messages_destination_icao", "destination_icao"),
        Index("idx_messages_frequency_hz", "frequency_hz"),
        Index("idx_messages_inserted_at", "inserted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    received_at: Mapped[str] = mapped_column(String, nullable=False)
    received_at_epoch_ms: Mapped[int | None] = mapped_column(Integer)
    station_id: Mapped[str | None] = mapped_column(String)
    frequency_hz: Mapped[int | None] = mapped_column(Integer)
    source_icao: Mapped[str | None] = mapped_column(String)
    destination_icao: Mapped[str | None] = mapped_column(String)
    direction: Mapped[str | None] = mapped_column(String)
    message_type: Mapped[str | None] = mapped_column(String)
    aircraft_registration: Mapped[str | None] = mapped_column(String)
    flight_id: Mapped[str | None] = mapped_column(String)
    message_text: Mapped[str | None] = mapped_column(String)
    raw_json: Mapped[str] = mapped_column(String, nullable=False)
    inserted_at: Mapped[str] = mapped_column(String, nullable=False)
    message_hash: Mapped[str] = mapped_column(String, nullable=False)


class CollectorState(Base):
    __tablename__ = "collector_state"

    spool_path: Mapped[str] = mapped_column(String, primary_key=True)
    byte_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


_factories: dict[str, sessionmaker] = {}


def _make_engine(db_path: str):
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


def _get_factory(db_path: str) -> sessionmaker:
    if db_path not in _factories:
        _factories[db_path] = sessionmaker(bind=_make_engine(db_path), expire_on_commit=False)
    return _factories[db_path]


def init_db(db_path: str | None = None) -> None:
    path = db_path or get_settings().database
    Base.metadata.create_all(_get_factory(path).kw["bind"])


@contextmanager
def get_session(db_path: str | None = None) -> Generator[Session, None, None]:
    path = db_path or get_settings().database
    session: Session = _get_factory(path)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
