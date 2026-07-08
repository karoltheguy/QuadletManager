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
    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.commit = AsyncMock()

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
    """Running init_db() twice on the same file must succeed (real duplicate columns)."""
    import core.database as db_module

    db_path = str(tmp_path / "test.db")
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = db_path
    try:
        await db_module.init_db()
        await db_module.init_db()  # Migrations hit real 'duplicate column name' errors
    finally:
        db_module.DATABASE_PATH = original
