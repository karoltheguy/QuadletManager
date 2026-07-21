"""
Tests for Issue #173: SQLite pragma configuration (WAL + busy_timeout + synchronous=NORMAL).

The app opens a fresh aiosqlite connection per request via ``get_db_connection()``
in core/database.py, and currently sets NO pragmas anywhere. It therefore runs on
SQLite's default rollback journal, whose database-wide write lock blocks readers -
risking "database is locked" under the stats engine's every-5s writes. The fix
will set WAL + busy_timeout + synchronous=NORMAL.

These tests are RED until that fix is implemented.
"""
import os
import sys
import pytest
import pytest_asyncio
import aiosqlite

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import core.database as db_module
from core.database import init_db, get_db_connection


# ── Fixture: isolated temp-file DB (mirrors tests/test_theme_customization.py) ──

@pytest_asyncio.fixture
async def fresh_db(tmp_path):
    """Run init_db() against a temp file and yield the path. Restores DATABASE_PATH after."""
    db_path = str(tmp_path / "test_pragmas.db")
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = db_path
    try:
        await init_db()
        yield db_path
    finally:
        db_module.DATABASE_PATH = original


# ── Pragma contract tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_journal_mode_is_wal_after_init_db(fresh_db):
    """journal_mode must be WAL after init_db(). WAL is persisted in the database
    file itself, so we can check it via a plain connection (not get_db_connection())."""
    async with aiosqlite.connect(fresh_db) as db:
        async with db.execute("PRAGMA journal_mode") as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row[0].lower() == "wal", f"expected journal_mode 'wal', got {row[0]!r}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_busy_timeout_is_5000_on_get_db_connection(fresh_db):
    """busy_timeout is PER-CONNECTION and is NOT persisted, so it must be set every
    time a connection is opened via get_db_connection()."""
    async with get_db_connection() as db:
        async with db.execute("PRAGMA busy_timeout") as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row[0] == 5000, f"expected busy_timeout 5000, got {row[0]!r}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_synchronous_is_normal_on_get_db_connection(fresh_db):
    """synchronous must be NORMAL (integer 1) on a connection from get_db_connection()."""
    async with get_db_connection() as db:
        async with db.execute("PRAGMA synchronous") as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row[0] == 1, f"expected synchronous 1 (NORMAL), got {row[0]!r}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_db_connection_still_works_as_async_context_manager(fresh_db):
    """Regression guard for the upcoming refactor.

    Implementing the busy_timeout and synchronous contracts above requires
    converting get_db_connection() from a plain function returning
    aiosqlite.connect(...) into an @asynccontextmanager that yields the
    connection after running pragmas. There are ~191
    `async with get_db_connection() as db:` call sites across the codebase;
    this test is the guard that the conversion keeps that calling convention
    working. It is expected to PASS already against the current plain-function
    implementation - it is not a red test, it just pins the contract.
    """
    async with get_db_connection() as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row[0] >= 0
