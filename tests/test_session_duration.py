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
def reset_session_duration():
    """Session duration is cached in-process; keep tests isolated from each other."""
    original = api_routes._session_duration_seconds
    yield
    api_routes._session_duration_seconds = original


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

        class DualProtocolCM:
            """Objects returned by aiosqlite execute() support both
            `async with obj` and `await obj`."""
            async def __aenter__(self):
                return cursor

            async def __aexit__(self, *args):
                return False

            def __await__(self):
                async def _resolve():
                    return cursor
                return _resolve().__await__()

        return DualProtocolCM()


@pytest.mark.unit
def test_session_duration_requires_admin(client):
    cookie = _login(client, is_admin=False)
    response = client.put(
        "/api/settings/session-duration",
        data={"session_duration_seconds": "604800"},
        cookies={"qm_session": cookie},
    )
    assert response.status_code == 403


@pytest.mark.unit
def test_session_duration_get_requires_admin(client):
    cookie = _login(client, is_admin=False)
    response = client.get(
        "/api/settings/session-duration",
        cookies={"qm_session": cookie},
    )
    assert response.status_code == 403


@pytest.mark.unit
def test_session_duration_rejects_invalid_value(client):
    cookie = _login(client, is_admin=True)
    response = client.put(
        "/api/settings/session-duration",
        data={"session_duration_seconds": "42"},
        cookies={"qm_session": cookie},
    )
    assert response.status_code == 400


@pytest.mark.unit
def test_session_duration_persists_and_applies_to_new_logins(client):
    admin_cookie = _login(client, is_admin=True)

    settings_db = SettingsMockDB()

    @asynccontextmanager
    async def _mock_settings_conn():
        yield settings_db

    with patch("api.routes.get_db_connection", side_effect=_mock_settings_conn):
        response = client.put(
            "/api/settings/session-duration",
            data={"session_duration_seconds": "604800"},
            cookies={"qm_session": admin_cookie},
        )
    assert response.status_code == 200
    assert api_routes._session_duration_seconds == 604800

    conn_factory, _ = _mock_login_db(is_admin=True)
    with patch("api.routes.get_db_connection", side_effect=conn_factory):
        login_response = client.post(
            "/login",
            data={"username": "someone", "password": "password123"},
            follow_redirects=False,
        )
    set_cookie_header = login_response.headers["set-cookie"]
    assert "Max-Age=604800" in set_cookie_header
