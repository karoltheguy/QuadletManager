"""Shared mocks for the admin settings endpoints.

`test_log_level.py` and `test_session_duration.py` both drive an admin-only
settings endpoint through the real app, so both need the same two fakes: a
login that yields an admin (or non-admin) session cookie, and an in-memory
stand-in for the `settings` key/value table. They previously carried
byte-identical copies of both.
"""
from contextlib import asynccontextmanager
from unittest.mock import patch, AsyncMock, MagicMock


def mock_login_db(is_admin: bool):
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


def login(client, is_admin: bool):
    """Log in through the real /login route and return the session cookie."""
    conn_factory, _ = mock_login_db(is_admin)
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


@asynccontextmanager
async def settings_conn(settings_db):
    """get_db_connection() replacement yielding the given SettingsMockDB."""
    yield settings_db
