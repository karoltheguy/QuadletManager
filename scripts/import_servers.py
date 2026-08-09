import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import get_db_connection
from core.crypto import encrypt_private_key


async def fetch_podman_connections():
    """Return podman's configured connections, or None if podman failed."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "podman", "system", "connection", "list", "--format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"podman exited {proc.returncode}: {stderr.decode(errors='replace').strip()}"
            )
        return json.loads(stdout)
    except Exception as e:
        print(f"Error fetching podman connections: {e}")
        return None


def parse_ssh_uri(uri: str) -> tuple[str, str]:
    """Split an ``ssh://[user@]host[:port]/...`` URI into (ssh_user, ip_address).

    The user defaults to root when the URI omits it, and the port is dropped.
    """
    user_host_port = uri[len("ssh://"):].split("/")[0]
    if "@" in user_host_port:
        ssh_user, host_port = user_host_port.split("@", 1)
    else:
        ssh_user = "root"
        host_port = user_host_port
    ip_address = host_port.split(":", 1)[0]
    return ssh_user, ip_address


async def read_identity_key(identity_path: str) -> str:
    """Read a private key file off the event loop thread."""
    # to_thread rather than a plain open(): the caller is async, and a
    # synchronous read blocks the event loop.
    return await asyncio.to_thread(
        Path(os.path.expanduser(identity_path)).read_text, encoding="utf-8"
    )


async def upsert_ssh_key(db, name: str, encrypted_key: str) -> int:
    """Insert or update the stored key for ``name`` and return its row id."""
    async with db.execute("SELECT id FROM ssh_keys WHERE key_name = ?", (name,)) as cursor:
        row = await cursor.fetchone()
    if row:
        key_id = row[0]
        await db.execute(
            "UPDATE ssh_keys SET encrypted_private_key = ? WHERE id = ?",
            (encrypted_key, key_id)
        )
        return key_id
    ins_cursor = await db.execute(
        "INSERT INTO ssh_keys (key_name, encrypted_private_key) VALUES (?, ?)",
        (name, encrypted_key)
    )
    return ins_cursor.lastrowid


async def upsert_server(db, name: str, ip_address: str, ssh_user: str, key_id: int) -> None:
    """Insert or update the server row for ``name``."""
    async with db.execute("SELECT id FROM servers WHERE name = ?", (name,)) as cursor:
        row = await cursor.fetchone()
    if row:
        print(f"Server {name} already exists. Updating...")
        await db.execute(
            "UPDATE servers SET ip_address = ?, ssh_user = ?, ssh_key_id = ? WHERE name = ?",
            (ip_address, ssh_user, key_id, name)
        )
        return
    await db.execute(
        "INSERT INTO servers (name, ip_address, ssh_user, ssh_key_id) VALUES (?, ?, ?, ?)",
        (name, ip_address, ssh_user, key_id)
    )
    print(f"Added server: {name} ({ssh_user}@{ip_address})")


async def import_connection(db, conn: dict) -> None:
    """Import one podman connection, skipping anything unusable."""
    name = conn.get("Name")
    uri = conn.get("URI")

    if not uri.startswith("ssh://"):
        print(f"Skipping {name} (not an ssh connection: {uri})")
        return

    ssh_user, ip_address = parse_ssh_uri(uri)

    identity_path = conn.get("Identity")
    try:
        private_key = await read_identity_key(identity_path)
    except Exception as e:
        print(f"Skipping {name} (Error reading key {identity_path}: {e})")
        return

    key_id = await upsert_ssh_key(db, name, encrypt_private_key(private_key))
    await upsert_server(db, name, ip_address, ssh_user, key_id)


async def main():
    print("Fetching server connections from podman...")
    connections = await fetch_podman_connections()
    if connections is None:
        return

    if not connections:
        print("No podman connections found.")
        return

    async with get_db_connection() as db:
        for conn in connections:
            await import_connection(db, conn)
        await db.commit()
    print("Done! You can now access these servers via the QuadletManager dashboard.")


if __name__ == "__main__":
    asyncio.run(main())
