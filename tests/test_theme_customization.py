"""
Tests for Theme Customization — Phase 1: Schema + seed (Issue #73).

Covers:
- user_themes table is created with the correct columns and constraints
- mode_preference CHECK constraint rejects invalid values
- _ensure_default_theme() inserts exactly one row on first call and is idempotent
- get_current_user_id() resolves the correct numeric id for a known user
"""
import os
import sys
import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import core.database as db_module
from core.database import init_db


# ── Fixture: isolated in-memory-style DB ──────────────────────────────────────

@pytest_asyncio.fixture
async def fresh_db(tmp_path):
    """Run init_db() against a temp file and yield the path. Restores DATABASE_PATH after."""
    db_path = str(tmp_path / "test_themes.db")
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = db_path
    try:
        await init_db()
        yield db_path
    finally:
        db_module.DATABASE_PATH = original


# ── Schema tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schema_init_creates_user_themes_table(fresh_db):
    """init_db() must create the user_themes table with all required columns."""
    async with aiosqlite.connect(fresh_db) as db:
        rows = await (await db.execute("PRAGMA table_info('user_themes')")).fetchall()

    assert rows, "user_themes table was not created by init_db()"

    col_names = [row[1] for row in rows]
    expected = {
        "id", "user_id", "theme_name", "mode_preference",
        "light_overrides_json", "dark_overrides_json",
        "is_active", "created_at", "updated_at",
    }
    missing = expected - set(col_names)
    assert not missing, f"user_themes is missing columns: {missing}"


@pytest.mark.asyncio
async def test_schema_init_creates_user_active_index(fresh_db):
    """init_db() must create the idx_user_themes_user_active index."""
    async with aiosqlite.connect(fresh_db) as db:
        rows = await (await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_user_themes_user_active'"
        )).fetchall()
    assert rows, "idx_user_themes_user_active index was not created"


@pytest.mark.asyncio
async def test_mode_preference_check_constraint(fresh_db):
    """Inserting an invalid mode_preference must raise an IntegrityError."""
    import time
    now = int(time.time())
    async with aiosqlite.connect(fresh_db) as db:
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                """INSERT INTO user_themes
                   (user_id, theme_name, mode_preference, created_at, updated_at)
                   VALUES (1, 'Bad Mode', 'weird', ?, ?)""",
                (now, now),
            )


@pytest.mark.asyncio
async def test_schema_idempotent_on_second_init(fresh_db):
    """Running init_db() a second time must not raise (idempotent migrations)."""
    await init_db()  # second call — should be a no-op


# ── _ensure_default_theme() tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_default_theme_seeds_once(fresh_db):
    """Calling _ensure_default_theme(user_id=1) must insert exactly one row."""
    from api.routes import _ensure_default_theme

    await _ensure_default_theme(user_id=1)

    async with aiosqlite.connect(fresh_db) as db:
        rows = await (await db.execute(
            "SELECT * FROM user_themes WHERE user_id=1"
        )).fetchall()

    assert len(rows) == 1, f"Expected 1 default theme row, got {len(rows)}"


@pytest.mark.asyncio
async def test_ensure_default_theme_is_idempotent(fresh_db):
    """Calling _ensure_default_theme() twice must still yield exactly one row."""
    from api.routes import _ensure_default_theme

    await _ensure_default_theme(user_id=1)
    await _ensure_default_theme(user_id=1)

    async with aiosqlite.connect(fresh_db) as db:
        rows = await (await db.execute(
            "SELECT * FROM user_themes WHERE user_id=1"
        )).fetchall()

    assert len(rows) == 1, f"Expected 1 row after two calls, got {len(rows)}"


@pytest.mark.asyncio
async def test_ensure_default_theme_is_active(fresh_db):
    """The seeded default theme must have is_active=1 and mode_preference='auto'."""
    from api.routes import _ensure_default_theme

    await _ensure_default_theme(user_id=1)

    async with aiosqlite.connect(fresh_db) as db:
        row = await (await db.execute(
            "SELECT theme_name, mode_preference, is_active FROM user_themes WHERE user_id=1"
        )).fetchone()

    assert row is not None
    theme_name, mode_pref, is_active = row
    assert theme_name == "Default"
    assert mode_pref == "auto"
    assert is_active == 1


# ── get_current_user_id() tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_current_user_id_returns_correct_id(fresh_db):
    """get_current_user_id returns the numeric id for a known username."""
    from api.routes import get_current_user_id

    result = await get_current_user_id(username="admin")
    assert result == 1, f"Expected id=1 for admin, got {result}"


@pytest.mark.asyncio
async def test_get_current_user_id_viewer(fresh_db):
    """get_current_user_id returns id=2 for the seeded viewer user."""
    from api.routes import get_current_user_id

    result = await get_current_user_id(username="viewer")
    assert result == 2, f"Expected id=2 for viewer, got {result}"


@pytest.mark.asyncio
async def test_get_current_user_id_missing_user_raises_404(fresh_db):
    """get_current_user_id raises HTTP 404 for an unknown username."""
    from fastapi import HTTPException
    from api.routes import get_current_user_id

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(username="ghost")

    assert exc_info.value.status_code == 404
