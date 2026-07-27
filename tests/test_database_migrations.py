"""Tests for init_db() migration error handling (PR #178).

Verifies that the additive-column migrations only swallow SQLite's
idempotent 'duplicate column name' error and propagate everything else
(locked database, disk full, corruption, ...).
"""
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.database import _is_duplicate_column_error, init_db


@pytest.mark.unit
def test_is_duplicate_column_error_matches_duplicate_column():
    exc = aiosqlite.OperationalError("duplicate column name: is_admin")
    assert _is_duplicate_column_error(exc)


@pytest.mark.unit
def test_is_duplicate_column_error_rejects_other_operational_errors():
    assert not _is_duplicate_column_error(aiosqlite.OperationalError("database is locked"))
    assert not _is_duplicate_column_error(ValueError("duplicate column name: x"))


def _mock_connect(execute_side_effect):
    """Build an aiosqlite.connect() replacement usable as an async context manager."""

    class _ExecuteResult:
        """Result of db.execute(...), usable both as `async with` and awaited directly.

        The new PRAGMA user_version read does `async with db.execute(...) as cur:
        row = await cur.fetchone()`, so the mocked execute() result must support
        both that async-context-manager usage and being awaited on its own for the
        plain `await db.execute(...)` calls used everywhere else.
        """

        async def fetchone(self):
            return (0,)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def __await__(self):
            async def _noop():
                return self
            return _noop().__await__()

    db = MagicMock()

    def _execute(sql, *args, **kwargs):
        # Must be synchronous (not an AsyncMock/coroutine function): real
        # aiosqlite db.execute() returns an object usable both as
        # `async with db.execute(...) as cur:` and as a plain awaitable, not
        # a coroutine itself. execute_side_effect may raise synchronously
        # here, matching real aiosqlite's ALTER TABLE error behavior.
        if execute_side_effect is not None:
            result = execute_side_effect(sql, *args, **kwargs)
            if result is not None:
                return result
        return _ExecuteResult()

    db.execute = MagicMock(side_effect=_execute)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
@pytest.mark.unit
async def test_init_db_propagates_non_duplicate_migration_errors():
    """A migration failing for a reason other than 'duplicate column' must raise."""
    def execute(sql, *args, **kwargs):
        if sql.strip().startswith("ALTER TABLE"):
            raise aiosqlite.OperationalError("database is locked")

    with patch("core.database.aiosqlite.connect", return_value=_mock_connect(execute)):
        with pytest.raises(aiosqlite.OperationalError, match="database is locked"):
            await init_db()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_init_db_tolerates_duplicate_column_errors():
    """The idempotent 'duplicate column name' error must not abort init_db()."""
    def execute(sql, *args, **kwargs):
        if sql.strip().startswith("ALTER TABLE"):
            raise aiosqlite.OperationalError("duplicate column name: whatever")

    connect_ctx = _mock_connect(execute)
    with patch("core.database.aiosqlite.connect", return_value=connect_ctx):
        await init_db()  # Must not raise


@pytest.mark.asyncio
@pytest.mark.unit
async def test_init_db_is_idempotent_against_real_database(tmp_path):
    """Running init_db() twice on the same file must succeed (real duplicate columns).

    The stored schema version is reset to 0 between the two calls because,
    with versioned migrations in place, a second init_db() call against an
    already-stamped database would otherwise skip all migrations and stop
    exercising the duplicate-column path this test exists to cover.
    """
    import aiosqlite
    import core.database as db_module

    db_path = str(tmp_path / "test.db")
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = db_path
    try:
        await db_module.init_db()

        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA user_version = 0")
            await db.commit()

        await db_module.init_db()  # Migrations hit real 'duplicate column name' errors
    finally:
        db_module.DATABASE_PATH = original
