from __future__ import annotations

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Message, get_session, init_db


@pytest.fixture
def auth_client(tmp_path):
    """TestClient with API key authentication enabled."""
    db = str(tmp_path / "test.db")
    init_db(db)

    test_settings = Settings(
        database=db,
        spool=str(tmp_path / "messages.jsonl"),
        api_key="test-secret-key",
    )

    def _settings():
        return test_settings

    def _session(path=None):
        return get_session(db)

    from app.main import app
    with patch("app.main.get_settings", _settings), \
         patch("app.main.init_db", lambda path=None: None), \
         patch("app.main.run_collector", lambda **_: None), \
         patch("app.main.purge_old_messages", lambda **_: 0), \
         patch("app.auth.get_settings", _settings), \
         patch("app.routes.messages.get_settings", _settings), \
         patch("app.routes.health.get_settings", _settings), \
         patch("app.models.get_session", _session), \
         patch("app.routes.health.get_session", _session):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def test_no_key_returns_401(auth_client):
    r = auth_client.get("/api/v1/messages")
    assert r.status_code == 401


def test_wrong_key_returns_401(auth_client):
    r = auth_client.get("/api/v1/messages", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_correct_key_returns_200(auth_client):
    r = auth_client.get("/api/v1/messages", headers={"X-API-Key": "test-secret-key"})
    assert r.status_code == 200


def test_health_requires_key(auth_client):
    assert auth_client.get("/api/v1/health").status_code == 401
    assert auth_client.get("/api/v1/health", headers={"X-API-Key": "test-secret-key"}).status_code == 200


def test_no_key_configured_allows_all(tmp_path):
    """When VDL2_API_KEY is empty, all requests pass through."""
    db = str(tmp_path / "test.db")
    init_db(db)

    test_settings = Settings(
        database=db,
        spool=str(tmp_path / "messages.jsonl"),
        api_key="",
    )

    def _settings():
        return test_settings

    def _session(path=None):
        return get_session(db)

    from app.main import app
    with patch("app.main.get_settings", _settings), \
         patch("app.main.init_db", lambda path=None: None), \
         patch("app.main.run_collector", lambda **_: None), \
         patch("app.main.purge_old_messages", lambda **_: 0), \
         patch("app.auth.get_settings", _settings), \
         patch("app.routes.messages.get_settings", _settings), \
         patch("app.routes.health.get_settings", _settings), \
         patch("app.models.get_session", _session), \
         patch("app.routes.health.get_session", _session):
        with TestClient(app, raise_server_exceptions=True) as c:
            assert c.get("/api/v1/messages").status_code == 200
