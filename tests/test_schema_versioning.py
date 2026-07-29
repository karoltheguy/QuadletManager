"""
Tests for Issue #172: versioned schema migrations via SQLite's PRAGMA user_version.

Right now init_db() runs its additive migrations unconditionally on every call
and never stamps the database with a schema version, so PRAGMA user_version stays
at 0 forever and the migration statements are re-executed on every startup.

These tests are RED until versioned migrations are implemented.
"""
import os
import sys
from unittest.mock import patch

import pytest
import pytest_asyncio
import aiosqlite

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import core.database as db_module
from core.database import init_db


# ── Helper: stamp PRAGMA user_version directly, simulating an unstamped or
# legacy-versioned database file without going through init_db() ────────────

async def _set_user_version(path, value):
    """Open the SQLite file at ``path`` and stamp ``PRAGMA user_version``."""
    async with aiosqlite.connect(path) as db:
        await db.execute(f"PRAGMA user_version = {value}")
        await db.commit()


# ── Fixture: isolated temp-file DB (mirrors tests/test_db_pragmas.py:26-36) ──

@pytest_asyncio.fixture
async def fresh_db_path(tmp_path):
    """Yield a fresh, non-existent temp-file DB path. Restores DATABASE_PATH after."""
    db_path = str(tmp_path / "test_schema_versioning.db")
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = db_path
    try:
        yield db_path
    finally:
        db_module.DATABASE_PATH = original


# ── Schema versioning contract tests ─────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_init_db_stamps_schema_version(fresh_db_path):
    """After init_db() runs, PRAGMA user_version must be stamped to at least 1."""
    await init_db()

    async with aiosqlite.connect(fresh_db_path) as db:
        async with db.execute("PRAGMA user_version") as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row[0] >= 1, f"expected PRAGMA user_version >= 1, got {row[0]!r}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_init_db_skips_migrations_when_version_current(fresh_db_path):
    """Once stamped at the current schema version, additive migrations must not
    be re-executed on a subsequent init_db() call against the same file."""
    await init_db()

    call_count = 0
    real_run_additive_migration = db_module._run_additive_migration

    async def counting_wrapper(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await real_run_additive_migration(*args, **kwargs)

    with patch("core.database._run_additive_migration", side_effect=counting_wrapper):
        await init_db()

    assert call_count == 0, f"expected 0 migration calls on second init_db(), got {call_count}"


# ── Real-world remigration and hardening scenarios ───────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_reordered_server_positions_survive_remigration(fresh_db_path):
    """Custom server ordering must not be reset when the baseline migration
    re-runs against an already-populated schema.

    ``ALTER TABLE servers ADD COLUMN position`` and ``UPDATE servers SET
    position = id`` are deliberately issued as a single ``_run_additive_migration``
    call. When the ALTER fails with 'duplicate column name' (because the
    column already exists), the whole statement list is skipped, so the
    UPDATE never runs. If these two statements are ever split into separate
    ``_run_additive_migration`` calls, the ALTER on the second call would be
    a no-op success (nothing to add) and the UPDATE would execute unconditionally,
    silently resetting every user's custom server ordering back to id order.
    This test is the guard against that regression.
    """
    await init_db()

    async with aiosqlite.connect(fresh_db_path) as db:
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (1, 's1', '10.0.0.1', 'root')"
        )
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (2, 's2', '10.0.0.2', 'root')"
        )
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (3, 's3', '10.0.0.3', 'root')"
        )
        await db.execute("UPDATE servers SET position = 30 WHERE id = 1")
        await db.execute("UPDATE servers SET position = 10 WHERE id = 2")
        await db.execute("UPDATE servers SET position = 20 WHERE id = 3")
        await db.commit()

    await _set_user_version(fresh_db_path, 0)

    await init_db()

    async with aiosqlite.connect(fresh_db_path) as db:
        async with db.execute("SELECT id, position FROM servers ORDER BY id") as cur:
            rows = await cur.fetchall()

    positions = {row[0]: row[1] for row in rows}
    assert positions == {1: 30, 2: 10, 3: 20}, f"expected positions unchanged, got {positions}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_existing_data_survives_restamping(fresh_db_path):
    """Re-running the baseline migration after resetting user_version to 0
    must not clobber existing data or overwrite customized seed rows."""
    await init_db()

    async with aiosqlite.connect(fresh_db_path) as db:
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (1, 'my-server', '10.0.0.5', 'root')"
        )
        await db.execute(
            "INSERT INTO ssh_keys (id, key_name, encrypted_private_key) VALUES (1, 'my-key', ?)",
            (b"encrypted-bytes",),
        )
        await db.execute("UPDATE templates SET content = 'CUSTOMIZED' WHERE id = 1")
        await db.commit()

    await _set_user_version(fresh_db_path, 0)

    await init_db()

    async with aiosqlite.connect(fresh_db_path) as db:
        async with db.execute("SELECT name, ip_address, ssh_user FROM servers WHERE id = 1") as cur:
            server_row = await cur.fetchone()
        async with db.execute("SELECT key_name, encrypted_private_key FROM ssh_keys WHERE id = 1") as cur:
            key_row = await cur.fetchone()
        async with db.execute("SELECT content FROM templates WHERE id = 1") as cur:
            template_row = await cur.fetchone()
        async with db.execute("PRAGMA user_version") as cur:
            version_row = await cur.fetchone()

    assert server_row == ("my-server", "10.0.0.5", "root")
    assert key_row == ("my-key", b"encrypted-bytes")
    assert template_row == ("CUSTOMIZED",)
    assert version_row[0] == db_module._SCHEMA_VERSION


@pytest.mark.asyncio
@pytest.mark.unit
async def test_partially_migrated_database_is_upgraded(fresh_db_path):
    """A database hand-built in the old (pre-#172) shape must be fully
    upgraded to the current schema by init_db(), preserving pre-existing rows."""
    async with aiosqlite.connect(fresh_db_path) as db:
        await db.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('viewer','editor'))
            )
        """)
        await db.execute("""
            CREATE TABLE ssh_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_name TEXT UNIQUE NOT NULL,
                encrypted_private_key BLOB NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                ssh_user TEXT NOT NULL,
                ssh_key_id INTEGER
            )
        """)
        await db.execute(
            "INSERT INTO users (id, username, password_hash, role) VALUES (100, 'legacy-user', 'hash', 'editor')"
        )
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (200, 'legacy-server', '10.1.1.1', 'root')"
        )
        await db.commit()

    await init_db()

    async with aiosqlite.connect(fresh_db_path) as db:
        async with db.execute("PRAGMA table_info(servers)") as cur:
            server_cols = {row[1] for row in await cur.fetchall()}
        async with db.execute("PRAGMA table_info(users)") as cur:
            user_cols = {row[1] for row in await cur.fetchall()}
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
            "('user_themes', 'container_events')"
        ) as cur:
            table_names = {row[0] for row in await cur.fetchall()}
        async with db.execute("SELECT username FROM users WHERE id = 100") as cur:
            user_row = await cur.fetchone()
        async with db.execute("SELECT name, ip_address, ssh_user FROM servers WHERE id = 200") as cur:
            server_row = await cur.fetchone()
        async with db.execute("PRAGMA user_version") as cur:
            version_row = await cur.fetchone()

    assert {"scope_filter", "position", "host_key"} <= server_cols
    assert {"is_admin", "must_change_password"} <= user_cols
    assert table_names == {"user_themes", "container_events"}
    assert user_row == ("legacy-user",)
    assert server_row == ("legacy-server", "10.1.1.1", "root")
    assert version_row[0] == db_module._SCHEMA_VERSION


@pytest.mark.asyncio
@pytest.mark.unit
async def test_failed_migration_rolls_back_and_leaves_version_unbumped(fresh_db_path, monkeypatch):
    """A migration that raises partway through must leave neither its partial
    schema changes nor a bumped user_version behind.

    This is what the explicit ``BEGIN`` in ``init_db()`` exists for: without
    it, a crash between the migration body and the version stamp would leave
    a stamped-but-unapplied schema on disk.
    """
    await init_db()
    applied_version = db_module._SCHEMA_VERSION

    async def failing_migration(db):
        await db.execute("CREATE TABLE should_not_survive (x INTEGER)")
        raise RuntimeError("boom")

    # Append onto the real registry rather than rebuilding it, so this stays
    # correct as further migrations are added.
    monkeypatch.setattr(
        db_module, "_MIGRATIONS", [*db_module._MIGRATIONS, failing_migration]
    )
    monkeypatch.setattr(db_module, "_SCHEMA_VERSION", applied_version + 1)

    with pytest.raises(RuntimeError, match="boom"):
        await init_db()

    async with aiosqlite.connect(fresh_db_path) as db:
        async with db.execute("PRAGMA user_version") as cur:
            version_row = await cur.fetchone()
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'should_not_survive'"
        ) as cur:
            table_row = await cur.fetchone()

    assert version_row[0] == applied_version, (
        f"expected user_version to remain {applied_version}, got {version_row[0]}"
    )
    assert table_row is None, "should_not_survive table must not persist after rollback"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_pending_migrations_run_in_order_from_stored_version(fresh_db_path, monkeypatch):
    """Only migrations at or above the stored version must run, and they
    must run in registry order.

    This pins the index-alignment convention that entry ``i`` of
    ``_MIGRATIONS`` moves the database from version ``i`` to version ``i+1``.
    """
    await init_db()
    applied_version = db_module._SCHEMA_VERSION

    order = []

    async def step_two(db):
        order.append("two")
        await db.execute("CREATE TABLE marker_two (x INTEGER)")

    async def step_three(db):
        order.append("three")
        await db.execute("CREATE TABLE marker_three (x INTEGER)")

    # Appended onto the real registry, so only these two are pending and the
    # already-applied migrations must not re-run.
    monkeypatch.setattr(
        db_module,
        "_MIGRATIONS",
        [*db_module._MIGRATIONS, step_two, step_three],
    )
    monkeypatch.setattr(db_module, "_SCHEMA_VERSION", applied_version + 2)

    await init_db()

    assert order == ["two", "three"]

    async with aiosqlite.connect(fresh_db_path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('marker_two', 'marker_three')"
        ) as cur:
            table_names = {row[0] for row in await cur.fetchall()}
        async with db.execute("PRAGMA user_version") as cur:
            version_row = await cur.fetchone()

    assert table_names == {"marker_two", "marker_three"}
    assert version_row[0] == applied_version + 2

    await init_db()

    assert order == ["two", "three"], "no migration should re-run on a subsequent init_db() call"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_newer_database_version_warns_and_skips(fresh_db_path, caplog):
    """A database stamped at a version newer than this release supports must
    trigger a warning and be left untouched, not downgraded."""
    await init_db()
    await _set_user_version(fresh_db_path, 99)

    with caplog.at_level("WARNING"):
        await init_db()

    assert any(
        "99" in record.getMessage() and str(db_module._SCHEMA_VERSION) in record.getMessage()
        for record in caplog.records
    ), f"expected a warning mentioning 99 and {db_module._SCHEMA_VERSION}, got: {[r.getMessage() for r in caplog.records]}"

    async with aiosqlite.connect(fresh_db_path) as db:
        async with db.execute("PRAGMA user_version") as cur:
            version_row = await cur.fetchone()

    assert version_row[0] == 99, f"expected user_version to remain 99, got {version_row[0]}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_set_schema_version_rejects_non_int(tmp_path):
    """``_set_schema_version`` interpolates its argument directly into a
    PRAGMA statement, so it must reject non-int and bool values (bool being
    a subclass of int in Python) to guard against that interpolation ever
    becoming an injection point."""
    db_path = str(tmp_path / "test_set_schema_version_rejects_non_int.db")

    async with aiosqlite.connect(db_path) as db:
        with pytest.raises(TypeError):
            await db_module._set_schema_version(db, "1")
        with pytest.raises(TypeError):
            await db_module._set_schema_version(db, True)
