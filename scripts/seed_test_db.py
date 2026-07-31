"""Seed a test database with the servers the browser-driven suites expect.

Two rows, seeded independently:

* "Mock Server": unchanged from the original script, kept exactly as it was so
  the existing e2e suite is unaffected. It has no ssh_key_id and therefore can
  never connect; it exists only to give the server tree something to render.

* "Podman Host": seeded only when QM_SEED_PODMAN is set, and unlike the mock
  server it is meant to actually work. connect_to_server() inner-joins ssh_keys,
  so a server row without a usable ssh_key_id is unreachable no matter what else
  is right; this row gets one.

The target address is deliberately not hardcoded. It differs by caller:
  CI (app container -> host container):  podman-host:22
  local, container target:               localhost:2223
  local, loopback target:                localhost:22

Environment (read identically here and in tests/podman/conftest.py):
  QM_PODMAN_HOST   default localhost:2223
  QM_PODMAN_USER   default editor
  QM_PODMAN_KEY    default tests/fixtures/test_key
  QM_SEED_PODMAN   when set, seed the Podman Host row too
"""

import asyncio
import os
import sys

import aiosqlite

from core.crypto import encrypt_private_key

KEY_NAME = "test_key"
MOCK_SERVER_NAME = "Mock Server"
PODMAN_SERVER_NAME = "Podman Host"


async def _ensure_ssh_key(db, key_path: str) -> int:
    """Insert the test private key, encrypted, and return its ssh_keys.id.

    Idempotent on the unique key_name, so re-running the seeder against a
    persistent volume neither duplicates nor re-encrypts.
    """
    async with db.execute("SELECT id FROM ssh_keys WHERE key_name = ?", (KEY_NAME,)) as cursor:
        row = await cursor.fetchone()
    if row:
        print(f"SSH key '{KEY_NAME}' already present (id={row[0]}).")
        return row[0]

    if not os.path.exists(key_path):
        raise SystemExit(f"SSH key not found at {key_path}; set QM_PODMAN_KEY.")

    with open(key_path, "r", encoding="utf-8") as handle:
        private_key = handle.read()

    cursor = await db.execute(
        "INSERT INTO ssh_keys (key_name, encrypted_private_key) VALUES (?, ?)",
        (KEY_NAME, encrypt_private_key(private_key)),
    )
    print(f"Seeded SSH key '{KEY_NAME}' from {key_path} (id={cursor.lastrowid}).")
    return cursor.lastrowid


async def _ensure_server(db, name: str, ip_address: str, ssh_user: str, ssh_key_id):
    """Insert one server row if a row with that name is not already there.

    host_key is left NULL on purpose. Host keys are TOFU-pinned on first
    connect, and a rebuilt container presents a new one; a stale pin raises
    HostKeyMismatchError against a reused database.
    """
    async with db.execute("SELECT id FROM servers WHERE name = ?", (name,)) as cursor:
        if await cursor.fetchone():
            print(f"Server '{name}' already seeded. Skipping.")
            return

    await db.execute(
        "INSERT INTO servers (name, ip_address, ssh_user, ssh_key_id, scope_filter) "
        "VALUES (?, ?, ?, ?, 'both')",
        (name, ip_address, ssh_user, ssh_key_id),
    )
    print(f"Seeded server '{name}' at {ssh_user}@{ip_address}.")


async def main():
    db_path = os.environ.get("QUADLET_DB_PATH", "/data/quadlets.db")
    seed_podman = bool(os.environ.get("QM_SEED_PODMAN"))

    if seed_podman and not os.environ.get("QUADLET_MASTER_KEY"):
        # Not fatal: core.crypto falls back to a persisted dev key. But the app
        # has to decrypt with the same key it was encrypted under, so a mismatch
        # here surfaces much later as an unexplained decryption failure.
        print(
            "warning: QUADLET_MASTER_KEY is unset; the key will be encrypted "
            "with a generated dev key, which must match the app's.",
            file=sys.stderr,
        )

    async with aiosqlite.connect(db_path) as db:
        # Unchanged behaviour for the mock server: only seeded into an empty
        # servers table, and still without an ssh_key_id.
        async with db.execute("SELECT COUNT(*) FROM servers") as cursor:
            is_empty = (await cursor.fetchone())[0] == 0
        if is_empty:
            await db.execute(
                "INSERT INTO servers (name, ip_address, ssh_user) VALUES (?, ?, ?)",
                (MOCK_SERVER_NAME, "localhost", "root"),
            )
            print("Database seeded with mock server.")
        else:
            print("Mock server already seeded. Skipping.")

        if seed_podman:
            key_id = await _ensure_ssh_key(
                db, os.environ.get("QM_PODMAN_KEY", "tests/fixtures/test_key")
            )
            await _ensure_server(
                db,
                PODMAN_SERVER_NAME,
                os.environ.get("QM_PODMAN_HOST", "localhost:2223"),
                os.environ.get("QM_PODMAN_USER", "editor"),
                key_id,
            )

        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
