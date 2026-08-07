"""
Tests for Issue #316: UNIQUE constraint and index on quadlets(server_id, file_path).

These tests are RED until the migration creating the unique index on quadlets(server_id, file_path)
and deduplicating existing rows is implemented in core/database.py.
"""
import os
import sys
import pytest
import pytest_asyncio
import aiosqlite

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import core.database as db_module
from core.database import init_db


# ── Fixture: isolated temp-file DB (mirrors tests/test_db_pragmas.py) ────────

@pytest_asyncio.fixture
async def fresh_db(tmp_path):
    """Run init_db() against a temp file and yield the path. Restores DATABASE_PATH after."""
    db_path = str(tmp_path / "test_quadlets_index.db")
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = db_path
    try:
        await init_db()
        yield db_path
    finally:
        db_module.DATABASE_PATH = original


# ── Quadlets Unique Index contract tests ─────────────────────────────────────

@pytest.mark.unit
async def test_duplicate_server_id_file_path_rejected(fresh_db):
    """Inserting a duplicate (server_id, file_path) pair into quadlets must raise IntegrityError."""
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute(
            "INSERT INTO quadlets (server_id, file_path, scope) VALUES (?, ?, ?)",
            (1, "/etc/containers/systemd/a.container", "global"),
        )
        await db.commit()

        # The constraint fires on execute, so the commit stays outside the
        # block: only one call in there may raise.
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO quadlets (server_id, file_path, scope) VALUES (?, ?, ?)",
                (1, "/etc/containers/systemd/a.container", "global"),
            )


@pytest.mark.unit
async def test_on_conflict_do_nothing_leaves_one_row(fresh_db):
    """ON CONFLICT(server_id, file_path) DO NOTHING must not raise and must leave 1 row."""
    stmt = (
        "INSERT INTO quadlets (server_id, file_path, scope) VALUES (?, ?, ?) "
        "ON CONFLICT(server_id, file_path) DO NOTHING"
    )
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute(stmt, (1, "/etc/containers/systemd/a.container", "global"))
        await db.execute(stmt, (1, "/etc/containers/systemd/a.container", "global"))
        await db.commit()

        async with db.execute("SELECT COUNT(*) FROM quadlets") as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row[0] == 1


@pytest.mark.unit
async def test_migration_dedupes_existing_rows(fresh_db):
    """Migration cleans up duplicate rows in an older database, preserving the lowest id."""
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute("DROP INDEX IF EXISTS idx_quadlets_server_path")
        await db.execute("PRAGMA user_version = 2")

        cursor1 = await db.execute(
            "INSERT INTO quadlets (server_id, file_path, scope) VALUES (?, ?, ?)",
            (1, "/etc/containers/systemd/dup.container", "global"),
        )
        id1 = cursor1.lastrowid

        cursor2 = await db.execute(
            "INSERT INTO quadlets (server_id, file_path, scope) VALUES (?, ?, ?)",
            (1, "/etc/containers/systemd/dup.container", "global"),
        )
        id2 = cursor2.lastrowid

        await db.execute(
            "INSERT INTO quadlets (server_id, file_path, scope) VALUES (?, ?, ?)",
            (1, "/etc/containers/systemd/other.container", "global"),
        )

        await db.commit()

    lowest_dup_id = min(id1, id2)

    await init_db()

    async with aiosqlite.connect(fresh_db) as db:
        async with db.execute("SELECT COUNT(*) FROM quadlets") as cur:
            row = await cur.fetchone()
        count = row[0] if row else 0

        async with db.execute(
            "SELECT id FROM quadlets WHERE file_path = ?",
            ("/etc/containers/systemd/dup.container",),
        ) as cur:
            dup_rows = await cur.fetchall()

    assert count == 2
    assert len(dup_rows) == 1
    assert dup_rows[0][0] == lowest_dup_id
