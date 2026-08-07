import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import get_db_connection
from core.crypto import encrypt_private_key

async def main():
    print("Fetching server connections from podman...")
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
        connections = json.loads(stdout)
    except Exception as e:
        print(f"Error fetching podman connections: {e}")
        return

    if not connections:
        print("No podman connections found.")
        return

    async with get_db_connection() as db:
        for conn in connections:
            name = conn.get("Name")
            uri = conn.get("URI")
            identity_path = conn.get("Identity")
            
            if not uri.startswith("ssh://"):
                print(f"Skipping {name} (not an ssh connection: {uri})")
                continue
                
            # Parse URI (e.g., ssh://user@host:22/...)
            parts = uri[6:].split("/")
            user_host_port = parts[0]
            if "@" in user_host_port:
                ssh_user, host_port = user_host_port.split("@", 1)
            else:
                ssh_user = "root"
                host_port = user_host_port
                
            if ":" in host_port:
                ip_address, _ = host_port.split(":", 1)
            else:
                ip_address = host_port
                
            # Read private key
            identity_path = os.path.expanduser(identity_path)
            try:
                # to_thread rather than a plain open(): this function is async,
                # and a synchronous read blocks the event loop.
                private_key = await asyncio.to_thread(
                    Path(identity_path).read_text, encoding="utf-8"
                )
            except Exception as e:
                print(f"Skipping {name} (Error reading key {identity_path}: {e})")
                continue
                
            encrypted_key = encrypt_private_key(private_key)
            
            # Check if key already exists
            async with db.execute("SELECT id FROM ssh_keys WHERE key_name = ?", (name,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    key_id = row[0]
                    await db.execute("UPDATE ssh_keys SET encrypted_private_key = ? WHERE id = ?", (encrypted_key, key_id))
                else:
                    ins_cursor = await db.execute(
                        "INSERT INTO ssh_keys (key_name, encrypted_private_key) VALUES (?, ?)",
                        (name, encrypted_key)
                    )
                    key_id = ins_cursor.lastrowid
            
            # Check if server already exists
            async with db.execute("SELECT id FROM servers WHERE name = ?", (name,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    print(f"Server {name} already exists. Updating...")
                    await db.execute(
                        "UPDATE servers SET ip_address = ?, ssh_user = ?, ssh_key_id = ? WHERE name = ?",
                        (ip_address, ssh_user, key_id, name)
                    )
                else:
                    await db.execute(
                        "INSERT INTO servers (name, ip_address, ssh_user, ssh_key_id) VALUES (?, ?, ?, ?)",
                        (name, ip_address, ssh_user, key_id)
                    )
                    print(f"Added server: {name} ({ssh_user}@{ip_address})")
                    
        await db.commit()
    print("Done! You can now access these servers via the QuadletManager dashboard.")

if __name__ == "__main__":
    asyncio.run(main())
