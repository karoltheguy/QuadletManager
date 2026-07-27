import os
import aiosqlite
import logging
from contextlib import asynccontextmanager
from typing import Sequence

logger = logging.getLogger("quadlet-manager.db")

DATABASE_PATH = os.environ.get("QUADLET_DB_PATH", "quadlets.db")

# Baseline squash: version 1 IS the current schema. Bump this whenever a new
# entry is appended to _MIGRATIONS.
_SCHEMA_VERSION = 1


def _is_duplicate_column_error(exc: Exception) -> bool:
    """True only for SQLite's idempotent 'duplicate column' ALTER TABLE error.

    Used to make additive column migrations safe to re-run without masking
    genuine failures (locked database, disk full, corruption) behind a blanket
    ``except Exception: pass``.
    """
    return isinstance(exc, aiosqlite.OperationalError) and "duplicate column name" in str(exc).lower()


async def _run_additive_migration(db, statements: Sequence[str]):
    """Run additive schema-migration statements, tolerating re-runs.

    Only 'duplicate column name' is swallowed; any other OperationalError
    (locked database, disk full, corruption) is re-raised. If the first
    statement fails with duplicate-column, remaining statements are
    skipped (matches original per-block try semantics).
    """
    try:
        for stmt in statements:
            await db.execute(stmt)
    except aiosqlite.OperationalError as exc:
        if not _is_duplicate_column_error(exc):
            raise  # Only 'column already exists' is expected here


async def _get_schema_version(db) -> int:
    """Read the schema version stamped via ``PRAGMA user_version``.

    Returns 0 if the database has never been stamped.
    """
    async with db.execute("PRAGMA user_version") as cur:
        row = await cur.fetchone()
    return row[0] if row is not None else 0


async def _set_schema_version(db, version: int):
    """Stamp the schema version via ``PRAGMA user_version``.

    SQLite pragmas do not accept bound parameters, so ``version`` must be
    interpolated directly into the SQL string. It is therefore guarded to
    only ever be an ``int`` (rejecting ``bool``, which is a subclass of
    ``int`` in Python) so this interpolation can never become an injection
    point.
    """
    if isinstance(version, bool) or not isinstance(version, int):
        raise TypeError(f"version must be an int, got {type(version).__name__}")
    await db.execute(f"PRAGMA user_version = {version}")


async def _migration_001_baseline(db):
    """Baseline squash: the entire schema as of Issue #172.

    Version 1 IS the current schema. This function is the ordered history
    up to this point, collapsed into a single migration.
    """
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('viewer', 'editor')),
            is_admin INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Migration: add is_admin column to existing databases
    await _run_additive_migration(db, [
        "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
    ])

    # Migration: add must_change_password column to existing databases
    await _run_additive_migration(db, [
        "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
    ])

    await db.execute("""
        CREATE TABLE IF NOT EXISTS ssh_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_name TEXT UNIQUE NOT NULL,
            encrypted_private_key BLOB NOT NULL
        )
    """)
    
    await db.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            ssh_user TEXT NOT NULL,
            ssh_key_id INTEGER,
            scope_filter TEXT NOT NULL DEFAULT 'both' CHECK(scope_filter IN ('user', 'global', 'both')),
            host_key TEXT,
            FOREIGN KEY(ssh_key_id) REFERENCES ssh_keys(id)
        )
    """)
    # Migration: add scope_filter column to existing databases
    await _run_additive_migration(db, [
        "ALTER TABLE servers ADD COLUMN scope_filter TEXT NOT NULL DEFAULT 'both' CHECK(scope_filter IN ('user', 'global', 'both'))"
    ])

    # Migration: add position column for user-defined server ordering
    await _run_additive_migration(db, [
        "ALTER TABLE servers ADD COLUMN position INTEGER NOT NULL DEFAULT 0",
        "UPDATE servers SET position = id"
    ])

    # Migration: add host_key column for TOFU SSH host-key pinning
    await _run_additive_migration(db, [
        "ALTER TABLE servers ADD COLUMN host_key TEXT"
    ])
    
    await db.execute("""
        CREATE TABLE IF NOT EXISTS quadlets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            scope TEXT NOT NULL CHECK(scope IN ('global', 'user')),
            last_known_mtime INTEGER,
            last_content_hash TEXT,
            FOREIGN KEY(server_id) REFERENCES servers(id)
        )
    """)
    
    await db.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('container', 'volume', 'network', 'pod')),
            content TEXT NOT NULL
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS container_health_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            container_name TEXT NOT NULL,
            is_running INTEGER NOT NULL DEFAULT 1,
            cpu_pct REAL DEFAULT 0,
            mem_pct REAL DEFAULT 0,
            recorded_at INTEGER NOT NULL,
            resolution_sec INTEGER NOT NULL DEFAULT 5,
            health_status TEXT DEFAULT NULL,
            FOREIGN KEY(server_id) REFERENCES servers(id)
        )
    """)

    # Migration: add health_status column to existing databases
    await _run_additive_migration(db, [
        "ALTER TABLE container_health_history ADD COLUMN health_status TEXT DEFAULT NULL"
    ])

    # Migration: add resolution_sec column to existing databases
    await _run_additive_migration(db, [
        "ALTER TABLE container_health_history ADD COLUMN resolution_sec INTEGER NOT NULL DEFAULT 5"
    ])

    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_health_history_server_time
        ON container_health_history(server_id, recorded_at)
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS container_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            container_name TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK(event_type IN ('start', 'stop', 'restart', 'failure')),
            triggered_by TEXT,
            details TEXT,
            occurred_at INTEGER NOT NULL,
            FOREIGN KEY(server_id) REFERENCES servers(id)
        )
    """)

    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_container_events_server_container
        ON container_events(server_id, container_name, occurred_at)
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS user_themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            theme_name TEXT NOT NULL,
            mode_preference TEXT NOT NULL DEFAULT 'auto'
                CHECK(mode_preference IN ('auto', 'light', 'dark')),
            light_overrides_json TEXT NOT NULL DEFAULT '{}',
            dark_overrides_json  TEXT NOT NULL DEFAULT '{}',
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, theme_name)
        )
    """)

    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_themes_user_active
        ON user_themes(user_id, is_active)
    """)

    # Seed basic templates if they do not exist
    await db.execute("INSERT OR IGNORE INTO templates (id, name, type, content) VALUES (1, 'Basic Container', 'container', '[Container]\\nImage=docker.io/library/nginx:latest\\nNetwork=host\\n')")
    await db.execute("INSERT OR IGNORE INTO templates (id, name, type, content) VALUES (2, 'Basic Volume', 'volume', '[Volume]\\nLabel=app=myapp\\n')")
    await db.execute("INSERT OR IGNORE INTO templates (id, name, type, content) VALUES (3, 'Basic Network', 'network', '[Network]\\nLabel=app=myapp\\n')")
    await db.execute("INSERT OR IGNORE INTO templates (id, name, type, content) VALUES (4, 'Basic Pod', 'pod', '[Pod]\\nPodName=mypod\\n')")
    
    # Seed default users (password is same as username)
    from argon2 import PasswordHasher
    ph = PasswordHasher()
    admin_hash = ph.hash("admin")
    viewer_hash = ph.hash("viewer")
    await db.execute("INSERT OR IGNORE INTO users (id, username, password_hash, role, is_admin, must_change_password) VALUES (1, 'admin', ?, 'editor', 1, 1)", (admin_hash,))
    await db.execute("INSERT OR IGNORE INTO users (id, username, password_hash, role, must_change_password) VALUES (2, 'viewer', ?, 'viewer', 1)", (viewer_hash,))
    # Ensure existing admin seed user has is_admin=1
    await db.execute("UPDATE users SET is_admin = 1 WHERE id = 1 AND is_admin = 0")


_MIGRATIONS = [_migration_001_baseline]


async def init_db():
    logger.info("Initializing SQLite Database Schema...")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # WAL is persisted in the database file itself, so this only needs
        # setting once here (not per-connection in get_db_connection()).
        # journal_mode=WAL must not run inside a transaction.
        await db.execute("PRAGMA journal_mode=WAL")
        # Prevent startup schema migrations from racing the stats engine.
        await db.execute("PRAGMA busy_timeout=5000")

        current_version = await _get_schema_version(db)

        if current_version > _SCHEMA_VERSION:
            logger.warning(
                "Database schema version %d is newer than this release supports (%d); "
                "skipping migrations.",
                current_version,
                _SCHEMA_VERSION,
            )
            return

        if current_version < len(_MIGRATIONS):
            logger.info(
                "Applying schema migrations from version %d to %d...",
                current_version,
                _SCHEMA_VERSION,
            )
        for index in range(current_version, len(_MIGRATIONS)):
            migration = _MIGRATIONS[index]
            await db.execute("BEGIN")
            try:
                await migration(db)
                await _set_schema_version(db, index + 1)
                await db.commit()
            except Exception:
                await db.rollback()
                raise


@asynccontextmanager
async def get_db_connection():
    """Yield an active connection to the SQLite database.

    Can be used as: ``async with get_db_connection() as db:``.

    Applies the per-connection pragmas ``busy_timeout=5000`` and
    ``synchronous=NORMAL`` (safe because WAL is enabled once in
    ``init_db()``) before yielding the connection.
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("PRAGMA synchronous=NORMAL")
        yield db
