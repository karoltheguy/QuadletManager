import aiosqlite
import logging

logger = logging.getLogger("quadlet-manager.db")

DATABASE_PATH = "quadlets.db"

async def init_db():
    logger.info("Initializing SQLite Database Schema...")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('viewer', 'editor'))
            )
        """)
        
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
                FOREIGN KEY(ssh_key_id) REFERENCES ssh_keys(id)
            )
        """)
        
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
        
        # Seed basic templates if they do not exist
        await db.execute("INSERT OR IGNORE INTO templates (id, name, type, content) VALUES (1, 'Basic Container', 'container', '[Container]\\nImage=docker.io/library/nginx:latest\\nNetwork=host\\n')")
        
        await db.commit()

async def get_db_connection():
    return await aiosqlite.connect(DATABASE_PATH)
