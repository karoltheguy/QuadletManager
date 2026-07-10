import os
import aiosqlite
import logging

logger = logging.getLogger("quadlet-manager.db")

DATABASE_PATH = os.environ.get("QUADLET_DB_PATH", "quadlets.db")


def _is_duplicate_column_error(exc: Exception) -> bool:
    """True only for SQLite's idempotent 'duplicate column' ALTER TABLE error.

    Used to make additive column migrations safe to re-run without masking
    genuine failures (locked database, disk full, corruption) behind a blanket
    ``except Exception: pass``.
    """
    return isinstance(exc, aiosqlite.OperationalError) and "duplicate column name" in str(exc).lower()


async def init_db():
    logger.info("Initializing SQLite Database Schema...")
    async with aiosqlite.connect(DATABASE_PATH) as db:
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
        try:
            await db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        except aiosqlite.OperationalError as exc:
            if not _is_duplicate_column_error(exc):
                raise  # Only 'column already exists' is expected here

        # Migration: add must_change_password column to existing databases
        try:
            await db.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
        except aiosqlite.OperationalError as exc:
            if not _is_duplicate_column_error(exc):
                raise  # Only 'column already exists' is expected here

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
                FOREIGN KEY(ssh_key_id) REFERENCES ssh_keys(id)
            )
        """)
        # Migration: add scope_filter column to existing databases
        try:
            await db.execute("ALTER TABLE servers ADD COLUMN scope_filter TEXT NOT NULL DEFAULT 'both' CHECK(scope_filter IN ('user', 'global', 'both'))")
        except aiosqlite.OperationalError as exc:
            if not _is_duplicate_column_error(exc):
                raise  # Only 'column already exists' is expected here

        # Migration: add position column for user-defined server ordering
        try:
            await db.execute("ALTER TABLE servers ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
            await db.execute("UPDATE servers SET position = id")
        except aiosqlite.OperationalError as exc:
            if not _is_duplicate_column_error(exc):
                raise  # Only 'column already exists' is expected here
        
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
        try:
            await db.execute("ALTER TABLE container_health_history ADD COLUMN health_status TEXT DEFAULT NULL")
        except aiosqlite.OperationalError as exc:
            if not _is_duplicate_column_error(exc):
                raise  # Only 'column already exists' is expected here

        # Migration: add resolution_sec column to existing databases
        try:
            await db.execute("ALTER TABLE container_health_history ADD COLUMN resolution_sec INTEGER NOT NULL DEFAULT 5")
        except aiosqlite.OperationalError as exc:
            if not _is_duplicate_column_error(exc):
                raise  # Only 'column already exists' is expected here

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
        
        await db.commit()

def get_db_connection():
    """Return an active connection context manager for the SQLite database.

    Can be used as: ``async with get_db_connection() as db:``.
    """
    return aiosqlite.connect(DATABASE_PATH)
