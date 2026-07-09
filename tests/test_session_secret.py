import os
import sys
import secrets

import pytest
import pytest_asyncio
import aiosqlite
import itsdangerous

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# ── Fixture: isolated DB for ensure_session_secret tests ─────────────────────

@pytest_asyncio.fixture
async def fresh_db(tmp_path):
    """Run init_db() against a temp database and restore DATABASE_PATH afterwards."""
    import core.database as db_module
    db_path = str(tmp_path / "test.db")
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = db_path
    try:
        await db_module.init_db()
        yield db_path
    finally:
        db_module.DATABASE_PATH = original


@pytest_asyncio.fixture
async def saved_routes_state():
    """Save/restore api.routes.SESSION_SECRET and api.routes.serializer, and clean the env var."""
    import api.routes as routes
    original_secret = routes.SESSION_SECRET
    original_serializer = routes.serializer
    original_env = os.environ.pop("QUADLET_SESSION_SECRET", None)
    try:
        yield routes
    finally:
        routes.SESSION_SECRET = original_secret
        routes.serializer = original_serializer
        if original_env is not None:
            os.environ["QUADLET_SESSION_SECRET"] = original_env
        else:
            os.environ.pop("QUADLET_SESSION_SECRET", None)


# ── ensure_session_secret tests ───────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_generates_and_persists_secret(fresh_db, saved_routes_state):
    """When no env var is set, ensure_session_secret generates a secret and stores it in the DB."""
    import core.database as db_module
    routes = saved_routes_state
    original_db = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = fresh_db
    try:
        os.environ.pop("QUADLET_SESSION_SECRET", None)
        await routes.ensure_session_secret()

        async with aiosqlite.connect(fresh_db) as db:
            async with db.execute(
                "SELECT value FROM settings WHERE key = 'session_secret'"
            ) as cursor:
                row = await cursor.fetchone()

        assert row is not None
        assert routes.SESSION_SECRET == row[0]
    finally:
        db_module.DATABASE_PATH = original_db


@pytest.mark.asyncio
@pytest.mark.unit
async def test_reuses_persisted_secret(fresh_db, saved_routes_state):
    """Calling ensure_session_secret twice reuses the same persisted secret."""
    import core.database as db_module
    routes = saved_routes_state
    original_db = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = fresh_db
    try:
        os.environ.pop("QUADLET_SESSION_SECRET", None)

        await routes.ensure_session_secret()
        first_secret = routes.SESSION_SECRET

        await routes.ensure_session_secret()
        second_secret = routes.SESSION_SECRET

        assert first_secret == second_secret

        async with aiosqlite.connect(fresh_db) as db:
            async with db.execute(
                "SELECT value FROM settings WHERE key = 'session_secret'"
            ) as cursor:
                rows = await cursor.fetchall()

        assert len(rows) == 1
        assert rows[0][0] == first_secret
    finally:
        db_module.DATABASE_PATH = original_db


@pytest.mark.asyncio
@pytest.mark.unit
async def test_env_var_wins_and_is_not_persisted(fresh_db, saved_routes_state, monkeypatch):
    """If QUADLET_SESSION_SECRET is set, it must be used and never written to the DB."""
    import core.database as db_module
    routes = saved_routes_state
    original_db = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = fresh_db
    try:
        known_value = "known-session-secret-value"
        monkeypatch.setenv("QUADLET_SESSION_SECRET", known_value)

        await routes.ensure_session_secret()

        assert routes.SESSION_SECRET == known_value

        async with aiosqlite.connect(fresh_db) as db:
            async with db.execute(
                "SELECT value FROM settings WHERE key = 'session_secret'"
            ) as cursor:
                row = await cursor.fetchone()

        assert row is None
    finally:
        db_module.DATABASE_PATH = original_db


@pytest.mark.asyncio
@pytest.mark.unit
async def test_cookie_survives_restart(fresh_db, saved_routes_state):
    """A cookie created before a simulated restart must still be readable after
    ensure_session_secret restores the persisted secret."""
    import core.database as db_module
    routes = saved_routes_state
    original_db = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = fresh_db
    try:
        os.environ.pop("QUADLET_SESSION_SECRET", None)

        await routes.ensure_session_secret()
        cookie = routes._create_session_cookie("alice", "user")

        # Simulate a process restart: fresh random SESSION_SECRET/serializer,
        # as would happen at import time before ensure_session_secret runs.
        routes.SESSION_SECRET = secrets.token_hex(32)
        routes.serializer = itsdangerous.URLSafeTimedSerializer(routes.SESSION_SECRET)

        await routes.ensure_session_secret()

        data = routes._read_session_cookie(cookie)

        assert data is not None
        assert data.get("username") == "alice"
    finally:
        db_module.DATABASE_PATH = original_db
