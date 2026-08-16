from __future__ import annotations

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.database import Message, get_session, init_db, _get_factory
from app.config import Settings


SAMPLE_ROWS = [
    dict(
        received_at="2026-08-16T16:24:09.000Z",
        received_at_epoch_ms=1786897449000,
        station_id="adsb-pi",
        frequency_hz=136975000,
        source_icao="4CADF7",
        destination_icao="1099CA",
        direction="downlink",
        message_type="H1",
        aircraft_registration="EIEXS",
        flight_id="EI501",
        message_text="#DFB",
        raw_json='{"t":1786897449,"freq":136975000,"avlc":{"src":{"addr":"4CADF7","type":"Aircraft"},"dst":{"addr":"1099CA","type":"Ground station"}}}',
        inserted_at="2026-08-16T16:24:09.100Z",
        message_hash="hash1",
    ),
    dict(
        received_at="2026-08-16T16:24:12.000Z",
        received_at_epoch_ms=1786897452000,
        station_id="adsb-pi",
        frequency_hz=136725000,
        source_icao="406A6E",
        destination_icao="1099CA",
        direction="downlink",
        message_type=None,
        aircraft_registration=None,
        flight_id=None,
        message_text=None,
        raw_json='{"t":1786897452,"freq":136725000,"avlc":{"src":{"addr":"406A6E","type":"Aircraft"},"dst":{"addr":"1099CA","type":"Ground station"}}}',
        inserted_at="2026-08-16T16:24:12.100Z",
        message_hash="hash2",
    ),
]


@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "test.db")
    init_db(db)
    with get_session(db) as session:
        for row in SAMPLE_ROWS:
            session.add(Message(**row))

    test_settings = Settings(
        database=db,
        spool=str(tmp_path / "messages.jsonl"),
    )

    def _settings():
        return test_settings

    def _session(path=None):
        return get_session(db)

    from app.main import app
    with patch("app.main.get_settings", _settings), \
         patch("app.main.init_db", lambda path=None: None), \
         patch("app.main.run_collector", lambda stop_event=None: None), \
         patch("app.main.purge_old_messages", lambda **_: 0), \
         patch("app.routes.messages.get_settings", _settings), \
         patch("app.routes.aircraft.get_settings", _settings), \
         patch("app.routes.stats.get_settings", _settings), \
         patch("app.routes.health.get_settings", _settings), \
         patch("app.models.get_session", _session), \
         patch("app.routes.aircraft.get_session", _session), \
         patch("app.routes.stats.get_session", _session), \
         patch("app.routes.health.get_session", _session):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ---------------------------------------------------------------------------
# /api/v1/messages
# ---------------------------------------------------------------------------

def test_list_messages_returns_all(client):
    body = client.get("/api/v1/messages").json()
    assert body["count"] == 2
    assert body["has_more"] is False


def test_after_id_cursor(client):
    body = client.get("/api/v1/messages?after_id=1").json()
    assert body["count"] == 1
    assert body["messages"][0]["id"] == 2


def test_after_id_beyond_last_returns_empty(client):
    body = client.get("/api/v1/messages?after_id=9999").json()
    assert body["count"] == 0
    assert body["first_id"] is None
    assert body["last_id"] is None
    assert body["has_more"] is False


def test_limit_and_has_more(client):
    body = client.get("/api/v1/messages?limit=1").json()
    assert body["count"] == 1
    assert body["has_more"] is True


def test_icao_filter(client):
    body = client.get("/api/v1/messages?icao=4CADF7").json()
    assert body["count"] == 1
    assert body["messages"][0]["source"]["icao"] == "4CADF7"


def test_icao_filter_case_insensitive(client):
    assert client.get("/api/v1/messages?icao=4cadf7").json()["count"] == 1


def test_frequency_filter(client):
    body = client.get("/api/v1/messages?frequency=136975000").json()
    assert body["count"] == 1
    assert body["messages"][0]["frequency_hz"] == 136975000


def test_message_shape(client):
    msg = client.get("/api/v1/messages?limit=1").json()["messages"][0]
    for key in ("id", "timestamp", "timestamp_ms", "ingested_at", "source", "destination", "raw"):
        assert key in msg


def test_raw_field_is_object(client):
    assert isinstance(client.get("/api/v1/messages?limit=1").json()["messages"][0]["raw"], dict)


def test_timestamp_format(client):
    ts = client.get("/api/v1/messages?limit=1").json()["messages"][0]["timestamp"]
    assert ts.endswith("Z") and "T" in ts


def test_since_filter(client):
    # since after the first message timestamp — should return only the second
    body = client.get("/api/v1/messages?since=2026-08-16T16:24:10.000Z").json()
    assert body["count"] == 1
    assert body["messages"][0]["id"] == 2


def test_until_filter(client):
    # until before the second message timestamp — should return only the first
    body = client.get("/api/v1/messages?until=2026-08-16T16:24:10.000Z").json()
    assert body["count"] == 1
    assert body["messages"][0]["id"] == 1


def test_since_malformed_returns_422(client):
    r = client.get("/api/v1/messages?since=not-a-date")
    assert r.status_code == 422


def test_until_malformed_returns_422(client):
    r = client.get("/api/v1/messages?until=yesterday")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# /api/v1/messages/latest
# ---------------------------------------------------------------------------

def test_latest_returns_newest_first(client):
    body = client.get("/api/v1/messages/latest?limit=10").json()
    assert body["count"] == 2
    assert body["messages"][0]["id"] > body["messages"][1]["id"]
    # For /latest: last_id is the newest (highest id), first_id is the oldest
    assert body["last_id"] == body["messages"][0]["id"]
    assert body["first_id"] == body["messages"][1]["id"]


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
