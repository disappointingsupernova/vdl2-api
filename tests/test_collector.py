import os
import pytest

from app.database import CollectorState, Message, get_session, init_db, _get_factory
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
    expected = sum(1 for line in open(FIXTURE) if line.strip())
    with open(FIXTURE) as fh:
        n = drain(fh, db, FIXTURE)
    assert n == expected


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
    assert n == 0


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
    with get_session(db) as session:
        count_after_first = session.query(Message).count()

    run_collector(spool_path=spool, db_path=db, poll_interval=0, _stop_after=1)
    with get_session(db) as session:
        count_after_second = session.query(Message).count()

    assert count_after_first == 1
    assert count_after_second == 1


# ---------------------------------------------------------------------------
# Rotation detection
# ---------------------------------------------------------------------------

def test_rotation_drains_old_file_and_switches_to_new(env, tmp_path):
    """
    Verify the rotation detection logic: when _inode() returns a different
    value for the spool path, the collector drains the current file handle
    and reopens the spool.

    We mock _inode to control when rotation appears to occur, and intercept
    the drain-of-old-file call to write the new spool content at the right
    moment. Both pre- and post-rotation messages must end up in the database.

    Platform note — Windows vs Linux:
    On Linux (production), dumpvdl2 renames the spool file and creates a new
    one. The inode of the path changes, the collector drains the old open
    file handle (which remains valid after rename), then reopens the path.
    This test mocks _inode() to simulate the inode change and uses content
    replacement + checkpoint reset as a stand-in for the rename, because
    Windows locks open files and os.rename() raises PermissionError.

    The mock covers the detection and reopen logic correctly. The one path
    not exercised on Windows is draining a renamed file via its old handle
    after the path has been replaced — that requires an actual rename and
    is best covered by a CI job running on Linux (e.g. GitHub Actions ubuntu
    runner), where os.rename() works on open files.
    """
    from unittest.mock import patch as mock_patch
    from app.collector import drain as real_drain

    db, _ = env
    spool = str(tmp_path / "messages.jsonl")

    line1 = '{"t":1786897449,"freq":136975000,"station_id":"s","avlc":{"src":{"addr":"AAAAAA","type":"Aircraft"},"dst":{"addr":"1099CA","type":"Ground station"}}}'
    line2 = '{"t":1786897512,"freq":136975000,"station_id":"s","avlc":{"src":{"addr":"BBBBBB","type":"Aircraft"},"dst":{"addr":"1099CA","type":"Ground station"}}}'

    _write_spool(spool, [line1])

    # inode sequence:
    #   call 1 (open)           → 100  sets current_inode
    #   call 2 (rotation check) → 100  no rotation; drain AAAAAA
    #   call 3 (rotation check) → 200  rotation detected
    #   call 4 (open new file)  → 200  sets current_inode
    #   call 5 (rotation check) → 200  stable; drain BBBBBB
    inode_seq = iter([100, 100, 200, 200, 200, 200])

    def _fake_inode(path):
        return next(inode_seq, 200)

    rotation_drained = [False]

    drain_calls = []

    def _fake_drain(fh, db_path, spool_path):
        drain_calls.append(spool_path)
        result = real_drain(fh, db_path, spool_path)
        if not rotation_drained[0]:
            rotation_drained[0] = True
            # Write new content to spool and reset the checkpoint so the
            # collector reads from offset 0 on reopen (simulates a new file).
            _write_spool(spool, [line2])
            save_offset(db, spool, 0)
        return result

    with mock_patch("app.collector._inode", side_effect=_fake_inode), \
         mock_patch("app.collector.time.sleep", return_value=None), \
         mock_patch("app.collector.drain", side_effect=_fake_drain):
        run_collector(spool_path=spool, db_path=db, poll_interval=0.001, _stop_after=8)

    with get_session(db) as session:
        icaos = {m.source_icao for m in session.query(Message).all()}

    assert "AAAAAA" in icaos, "Pre-rotation message not found"
    assert "BBBBBB" in icaos, "Post-rotation message not found"

def test_purge_old_messages(env):
    db, _ = env
    from sqlalchemy import text
    engine = _get_factory(db).kw["bind"]
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO messages (received_at, raw_json, inserted_at, message_hash) "
            "VALUES ('2026-01-01T00:00:00Z', '{}', datetime('now', '-31 days'), 'oldhash')"
        ))
    deleted = purge_old_messages(db_path=db, retention_days=30)
    assert deleted == 1
    with get_session(db) as session:
        assert session.query(Message).count() == 0


def test_purge_keeps_recent_messages(env):
    db, _ = env
    from sqlalchemy import text
    engine = _get_factory(db).kw["bind"]
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO messages (received_at, raw_json, inserted_at, message_hash) "
            "VALUES ('2026-08-15T00:00:00Z', '{}', datetime('now', '-1 days'), 'recenthash')"
        ))
    deleted = purge_old_messages(db_path=db, retention_days=30)
    assert deleted == 0
