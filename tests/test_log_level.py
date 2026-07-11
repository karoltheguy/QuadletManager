import logging

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from contextlib import asynccontextmanager
from fastapi.testclient import TestClient
from main import app
import api.routes as api_routes


@pytest.fixture
def client():
    with patch("core.config_loader.global_config.dev_auto_login", False):
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture(autouse=True)
def reset_log_level():
    """Log level is cached in-process; keep tests isolated from each other."""
    original = api_routes._log_level
    yield
    api_routes._log_level = original


def _mock_login_db(is_admin: bool):
    """Mock get_db_connection so /login authenticates as a user with the given admin flag."""
    from argon2 import PasswordHasher
    pwd_hash = PasswordHasher().hash("password123")

    class MockCursor:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
        async def fetchone(self):
            return (pwd_hash, "editor", int(is_admin), 0)

    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=MockCursor())
    mock_db.commit = AsyncMock()

    @asynccontextmanager
    async def _mock_conn():
        yield mock_db

    return _mock_conn, mock_db


def _login(client, is_admin: bool):
    conn_factory, _ = _mock_login_db(is_admin)
    with patch("api.routes.get_db_connection", side_effect=conn_factory):
        response = client.post(
            "/login",
            data={"username": "someone", "password": "password123"},
            follow_redirects=False,
        )
    return response.cookies["qm_session"]


class SettingsMockDB:
    """Minimal in-memory stand-in for the `settings` key/value table."""

    def __init__(self):
        self.store = {}

    async def commit(self):
        pass

    def execute(self, query, params=()):
        cursor = MagicMock()
        if query.strip().startswith("SELECT value FROM settings"):
            key = params[0]
            value = self.store.get(key)
            cursor.fetchone = AsyncMock(return_value=(value,) if value is not None else None)
        elif query.strip().startswith("INSERT INTO settings"):
            key, value = params
            self.store[key] = value
            cursor.fetchone = AsyncMock(return_value=None)
        else:
            cursor.fetchone = AsyncMock(return_value=None)

        async def _aenter():
            return cursor
        cursor.__aenter__ = AsyncMock(side_effect=_aenter)
        cursor.__aexit__ = AsyncMock(return_value=False)
        return cursor


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_log_level_ignores_invalid_stored_value():
    settings_db = SettingsMockDB()
    settings_db.store["log_level"] = "VERBOSE"

    @asynccontextmanager
    async def _mock_settings_conn():
        yield settings_db

    logger = logging.getLogger("quadlet-manager")
    original_level = logger.level

    with patch("api.routes.get_db_connection", side_effect=_mock_settings_conn):
        await api_routes._load_log_level_from_db()

    assert logger.level == original_level


@pytest.mark.unit
def test_log_level_persists_and_applies_live(client):
    admin_cookie = _login(client, is_admin=True)

    settings_db = SettingsMockDB()

    @asynccontextmanager
    async def _mock_settings_conn():
        yield settings_db

    with patch("api.routes.get_db_connection", side_effect=_mock_settings_conn):
        response = client.put(
            "/api/settings/log-level",
            data={"log_level": "DEBUG"},
            cookies={"qm_session": admin_cookie},
        )
    assert response.status_code == 200
    assert settings_db.store.get("log_level") == "DEBUG"
    assert logging.getLogger("quadlet-manager").level == logging.DEBUG
