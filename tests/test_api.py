"""
API integration tests.

Each test gets a fresh SQLite database via a TestClient that overrides
get_settings and get_connection so no real filesystem paths are needed.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.database import init_db, get_connection
from app.config import Settings


SAMPLE_ROWS = [
    {
        "received_at": "2026-08-16T16:24:09.000Z",
        "received_at_epoch_ms": 1786897449000,
        "station_id": "adsb-pi",
        "frequency_hz": 136975000,
        "source_icao": "4CADF7",
        "destination_icao": "1099CA",
        "direction": "downlink",
        "message_type": "H1",
        "aircraft_registration": "EIEXS",
        "flight_id": "EI501",
        "message_text": "#DFB",
        "raw_json": '{"t":1786897449,"freq":136975000,"avlc":{"src":{"addr":"4CADF7","type":"Aircraft"},"dst":{"addr":"1099CA","type":"Ground station"}}}',
        "inserted_at": "2026-08-16T16:24:09.100Z",
        "message_hash": "hash1",
    },
    {
        "received_at": "2026-08-16T16:24:12.000Z",
        "received_at_epoch_ms": 1786897452000,
        "station_id": "adsb-pi",
        "frequency_hz": 136725000,
        "source_icao": "406A6E",
        "destination_icao": "1099CA",
        "direction": "downlink",
        "message_type": None,
        "aircraft_registration": None,
        "flight_id": None,
        "message_text": None,
        "raw_json": '{"t":1786897452,"freq":136725000,"avlc":{"src":{"addr":"406A6E","type":"Aircraft"},"dst":{"addr":"1099CA","type":"Ground station"}}}',
        "inserted_at": "2026-08-16T16:24:12.100Z",
        "message_hash": "hash2",
    },
]

_INSERT = """
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


@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "test.db")
    init_db(db)
    conn = get_connection(db)
    for row in SAMPLE_ROWS:
        conn.execute(_INSERT, row)
    conn.commit()

    test_settings = Settings(
        database=db,
        spool=str(tmp_path / "messages.jsonl"),
        state=str(tmp_path / "collector.state"),
    )

    def _settings():
        return test_settings

    def _conn(path=None):
        return get_connection(db)

    def _noop_init(path=None):
        pass  # DB already initialised above

    def _noop_collector(**_kwargs):
        pass  # don't start background threads in tests

    from app.main import app
    with patch("app.main.get_settings", _settings), \
         patch("app.main.init_db", _noop_init), \
         patch("app.main.run_collector", _noop_collector), \
         patch("app.main.purge_old_messages", lambda **_: 0), \
         patch("app.routes.messages.get_settings", _settings), \
         patch("app.routes.aircraft.get_settings", _settings), \
         patch("app.routes.stats.get_settings", _settings), \
         patch("app.routes.health.get_settings", _settings), \
         patch("app.models.get_connection", _conn), \
         patch("app.routes.aircraft.get_connection", _conn), \
         patch("app.routes.stats.get_connection", _conn), \
         patch("app.routes.health.get_connection", _conn):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ---------------------------------------------------------------------------
# /api/v1/messages
# ---------------------------------------------------------------------------

def test_list_messages_returns_all(client):
    r = client.get("/api/v1/messages")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["has_more"] is False


def test_after_id_cursor(client):
    r = client.get("/api/v1/messages?after_id=1")
    body = r.json()
    assert body["count"] == 1
    assert body["messages"][0]["id"] == 2


def test_after_id_beyond_last_returns_empty(client):
    r = client.get("/api/v1/messages?after_id=9999")
    body = r.json()
    assert body["count"] == 0
    assert body["first_id"] is None
    assert body["last_id"] is None
    assert body["has_more"] is False


def test_limit_and_has_more(client):
    r = client.get("/api/v1/messages?limit=1")
    body = r.json()
    assert body["count"] == 1
    assert body["has_more"] is True


def test_icao_filter(client):
    r = client.get("/api/v1/messages?icao=4CADF7")
    body = r.json()
    assert body["count"] == 1
    assert body["messages"][0]["source"]["icao"] == "4CADF7"


def test_icao_filter_case_insensitive(client):
    r = client.get("/api/v1/messages?icao=4cadf7")
    body = r.json()
    assert body["count"] == 1


def test_frequency_filter(client):
    r = client.get("/api/v1/messages?frequency=136975000")
    body = r.json()
    assert body["count"] == 1
    assert body["messages"][0]["frequency_hz"] == 136975000


def test_message_shape(client):
    r = client.get("/api/v1/messages?limit=1")
    msg = r.json()["messages"][0]
    for key in ("id", "timestamp", "timestamp_ms", "ingested_at", "source", "destination", "raw"):
        assert key in msg


def test_raw_field_is_object(client):
    r = client.get("/api/v1/messages?limit=1")
    assert isinstance(r.json()["messages"][0]["raw"], dict)


def test_timestamp_format(client):
    ts = client.get("/api/v1/messages?limit=1").json()["messages"][0]["timestamp"]
    assert ts.endswith("Z") and "T" in ts


# ---------------------------------------------------------------------------
# /api/v1/messages/latest
# ---------------------------------------------------------------------------

def test_latest_returns_newest_first(client):
    body = client.get("/api/v1/messages/latest?limit=10").json()
    assert body["count"] == 2
    assert body["messages"][0]["id"] > body["messages"][1]["id"]


# ---------------------------------------------------------------------------
# /api/v1/aircraft/{icao}/messages
# ---------------------------------------------------------------------------

def test_aircraft_messages(client):
    body = client.get("/api/v1/aircraft/4CADF7/messages").json()
    assert body["count"] == 1
    assert body["messages"][0]["source"]["icao"] == "4CADF7"


def test_aircraft_messages_uppercase(client):
    assert client.get("/api/v1/aircraft/4cadf7/messages").json()["count"] == 1


# ---------------------------------------------------------------------------
# /api/v1/health
# ---------------------------------------------------------------------------

def test_health_ok(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["total_messages"] == 2


# ---------------------------------------------------------------------------
# /api/v1/stats
# ---------------------------------------------------------------------------

def test_stats_totals(client):
    body = client.get("/api/v1/stats").json()
    assert body["messages_total"] == 2
    assert isinstance(body["messages_by_frequency"], dict)
