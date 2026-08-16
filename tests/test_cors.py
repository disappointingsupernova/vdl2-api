"""
Tests for CORS middleware configuration.

Verifies that add_middleware() is called correctly inside _create_app()
and that the Origin header is reflected on preflight and simple requests.
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import get_session, init_db


def _cors_client(tmp_path, cors_origins: list[str]):
    """Build a TestClient from a freshly constructed app with the given CORS origins."""
    db = str(tmp_path / "test.db")
    init_db(db)

    test_settings = Settings(
        database=db,
        spool=str(tmp_path / "messages.jsonl"),
        cors_origins=",".join(cors_origins),
    )

    def _settings():
        return test_settings

    def _session(path=None):
        return get_session(db)

    # Import _create_app and build a fresh app instance inside the patch context
    # so that CORS middleware is configured with the test settings.
    from app.main import _create_app

    stack = ExitStack()
    stack.enter_context(patch("app.main.get_settings", _settings))
    stack.enter_context(patch("app.main.init_db", lambda path=None: None))
    stack.enter_context(patch("app.main.run_collector", lambda stop_event=None: None))
    stack.enter_context(patch("app.main.purge_old_messages", lambda **_: 0))
    stack.enter_context(patch("app.routes.messages.get_settings", _settings))
    stack.enter_context(patch("app.routes.health.get_settings", _settings))
    stack.enter_context(patch("app.models.get_session", _session))
    stack.enter_context(patch("app.routes.health.get_session", _session))

    fresh_app = _create_app()
    client = stack.enter_context(TestClient(fresh_app, raise_server_exceptions=False))
    return stack, client


def test_cors_allowed_origin_reflected(tmp_path):
    stack, c = _cors_client(tmp_path, ["http://dashboard.local"])
    with stack:
        r = c.options(
            "/api/v1/messages",
            headers={
                "Origin": "http://dashboard.local",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert r.headers.get("access-control-allow-origin") == "http://dashboard.local"


def test_cors_disallowed_origin_not_reflected(tmp_path):
    stack, c = _cors_client(tmp_path, ["http://dashboard.local"])
    with stack:
        r = c.options(
            "/api/v1/messages",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert r.headers.get("access-control-allow-origin") != "http://evil.example.com"


def test_cors_disabled_when_no_origins_configured(tmp_path):
    stack, c = _cors_client(tmp_path, [])
    with stack:
        r = c.options(
            "/api/v1/messages",
            headers={
                "Origin": "http://dashboard.local",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert "access-control-allow-origin" not in r.headers
