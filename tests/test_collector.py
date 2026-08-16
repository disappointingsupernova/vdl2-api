import os
import pytest
from sqlalchemy import text

from app.database import init_db, get_engine, get_conn
from app.collector import (
    drain,
    load_offset,
    save_offset,
    purge_old_messages,
    run_collector,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_messages.jsonl")


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / "test.db")
    spool = str(tmp_path / "messages.jsonl")
    init_db(db)
    return db, spool


def _write_spool(path, lines):
    with open(path, "w") as f:
        for line in lines:
            f.write(line + "\n")


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def test_offset_defaults_to_zero(env):
    db, spool = env
    assert load_offset(db, spool) == 0


def test_save_and_load_offset(env):
    db, spool = env
    save_offset(db, spool, 1234)
    assert load_offset(db, spool) == 1234


def test_save_offset_is_idempotent(env):
    db, spool = env
    save_offset(db, spool, 100)
    save_offset(db, spool, 200)
    assert load_offset(db, spool) == 200


# ---------------------------------------------------------------------------
# Drain
# ---------------------------------------------------------------------------

def test_drain_inserts_messages(env):
    db, spool = env
    with open(FIXTURE) as fh:
        n = drain(fh, db, FIXTURE)
    assert n == 4


def test_drain_skips_malformed(env, tmp_path):
    db, spool = env
    bad = str(tmp_path / "bad.jsonl")
    _write_spool(bad, ["{not json}", '{"t":1786897449,"freq":136975000,"station_id":"s","avlc":{}}'])
    with open(bad) as fh:
        n = drain(fh, db, bad)
    assert n == 1


def test_drain_deduplicates(env):
    db, spool = env
    with open(FIXTURE) as fh:
        drain(fh, db, FIXTURE)
    with open(FIXTURE) as fh:
        n = drain(fh, db, FIXTURE)
    assert n == 0  # all duplicates ignored


def test_drain_updates_checkpoint(env):
    db, spool = env
    with open(FIXTURE) as fh:
        drain(fh, db, FIXTURE)
    offset = load_offset(db, FIXTURE)
    assert offset == os.path.getsize(FIXTURE)


# ---------------------------------------------------------------------------
# Collector restart / checkpoint recovery
# ---------------------------------------------------------------------------

def test_collector_resumes_from_checkpoint(env, tmp_path):
    db, _ = env
    spool = str(tmp_path / "messages.jsonl")
    line = '{"t":1786897449,"freq":136975000,"station_id":"adsb-pi","avlc":{"src":{"addr":"4CADF7","type":"Aircraft"},"dst":{"addr":"1099CA","type":"Ground station"}}}'
    _write_spool(spool, [line])

    run_collector(spool_path=spool, db_path=db, poll_interval=0, _stop_after=1)
    with get_engine(db).connect() as conn:
        count_after_first = conn.execute(text("SELECT COUNT(*) FROM messages")).scalar()

    run_collector(spool_path=spool, db_path=db, poll_interval=0, _stop_after=1)
    with get_engine(db).connect() as conn:
        count_after_second = conn.execute(text("SELECT COUNT(*) FROM messages")).scalar()

    assert count_after_first == 1
    assert count_after_second == 1


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def test_purge_old_messages(env, tmp_path):
    db, _ = env
    with get_conn(db) as conn:
        conn.execute(text("""
            INSERT INTO messages (received_at, raw_json, inserted_at, message_hash)
            VALUES ('2026-01-01T00:00:00Z', '{}', datetime('now', '-31 days'), 'oldhash')
        """))
    deleted = purge_old_messages(db_path=db, retention_days=30)
    assert deleted == 1
    with get_engine(db).connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM messages")).scalar() == 0


def test_purge_keeps_recent_messages(env):
    db, _ = env
    with get_conn(db) as conn:
        conn.execute(text("""
            INSERT INTO messages (received_at, raw_json, inserted_at, message_hash)
            VALUES ('2026-08-15T00:00:00Z', '{}', datetime('now', '-1 days'), 'recenthash')
        """))
    deleted = purge_old_messages(db_path=db, retention_days=30)
    assert deleted == 0
