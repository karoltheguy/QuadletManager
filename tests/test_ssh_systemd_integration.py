import os
import pytest
import aiosqlite
from core.crypto import encrypt_private_key
from services.ssh_manager import pool
from services.systemd_manager import systemctl_action

@pytest.fixture
async def integration_db(tmp_path):
    """Sets up a real SQLite database for integration tests."""
    db_path = tmp_path / "integration.db"
    import core.database
    core.database.DATABASE_PATH = str(db_path)
    os.environ["QUADLET_DB_PATH"] = str(db_path)
    os.environ["QUADLET_MASTER_KEY"] = "0" * 64

    from core.database import init_db
    await init_db()

    # Create dummy key if not exists (in case it wasn't generated)
    key_path = "tests/fixtures/test_key"
    if not os.path.exists(key_path):
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        os.system(f'ssh-keygen -t ed25519 -f {key_path} -N ""')

    with open(key_path, "r") as f:
        priv_key = f.read()

    enc_key = encrypt_private_key(priv_key)

    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("INSERT INTO ssh_keys (key_name, encrypted_private_key) VALUES (?, ?)", ("test_key", enc_key))
        await db.execute("INSERT INTO servers (name, ip_address, ssh_user, ssh_key_id) VALUES (?, ?, ?, ?)",
                         ("Integration Test Server", "localhost:2222", "editor", 1))
        await db.commit()

    yield str(db_path)

    if "QUADLET_DB_PATH" in os.environ:
        del os.environ["QUADLET_DB_PATH"]

@pytest.mark.asyncio
async def test_ssh_connection_and_systemctl(integration_db):
    """Tests that we can connect via SSH and run systemctl on the test container."""
    await pool.close_all()
    
    # We use a try/except around the connection because if the docker-compose environment
    # isn't running, we should skip the test rather than fail it (similar to E2E tests).
    import socket
    try:
        with socket.create_connection(("localhost", 2222), timeout=1):
            pass
    except OSError:
        pytest.skip("Docker-compose test environment not running on localhost:2222")

    server_id = 1
    output = await pool.execute_command(server_id, "whoami", use_sudo=False)
    assert output.strip() == "editor"

    output_sudo = await pool.execute_command(server_id, "whoami", use_sudo=True)
    assert output_sudo.strip() == "root"

    # Test systemd manager
    res = await systemctl_action(server_id, "status", "ssh.service", scope="global", allow_failure=True)
    assert "active (running)" in res or "ssh.service" in res
