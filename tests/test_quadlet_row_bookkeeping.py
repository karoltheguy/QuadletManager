import asyncio
import hashlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from core.database import get_db_connection
from main import app


@pytest.fixture
def client():
    with patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as test_client:
            yield test_client


def _setup_server():
    async def _init():
        async with get_db_connection() as db:
            await db.execute(
                "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (1, 's1', '10.0.0.1', 'root')"
            )
            await db.commit()

    asyncio.run(_init())


@pytest.mark.unit
def test_create_quadlet_bookkeeping(client):
    _setup_server()

    with patch("api.routes.write_remote_file", new_callable=AsyncMock), \
         patch("api.routes.pool.execute_command", new_callable=AsyncMock) as mock_exec, \
         patch("api.routes.quadlet_dir_for_scope", new_callable=AsyncMock) as mock_dir, \
         patch("api.routes.reload_and_restart", new_callable=AsyncMock):

        mock_exec.return_value = "1700000000"
        mock_dir.return_value = "/home/quadlet/.config/containers/systemd"

        response = client.post(
            "/api/create",
            data={
                "server_id": 1,
                "scope": "user",
                "type": "container",
                "name": "myapp",
            },
            follow_redirects=False,
        )
        assert response.status_code == 200

        async def _check():
            async with get_db_connection() as db:
                async with db.execute(
                    "SELECT server_id, file_path, scope, last_known_mtime FROM quadlets WHERE server_id = 1"
                ) as cur:
                    return await cur.fetchall()

        rows = asyncio.run(_check())
        expected_path = "/home/quadlet/.config/containers/systemd/myapp.container"
        assert len(rows) == 1
        assert rows[0][1] == expected_path
        assert rows[0][2] == "user"
        assert rows[0][3] is not None


@pytest.mark.unit
def test_save_quadlet_new_file_bookkeeping(client):
    _setup_server()

    with patch("api.routes.write_remote_file", new_callable=AsyncMock), \
         patch("api.routes.pool.execute_command", new_callable=AsyncMock) as mock_exec, \
         patch("api.routes.quadlet_dir_for_scope", new_callable=AsyncMock) as mock_dir, \
         patch("api.routes.reload_and_restart", new_callable=AsyncMock):

        mock_exec.return_value = "1700000000"
        mock_dir.return_value = "/home/quadlet/.config/containers/systemd"

        file_path = "/home/quadlet/.config/containers/systemd/myapp.container"
        response = client.post(
            "/api/save",
            data={
                "server_id": 1,
                "file_path": file_path,
                "scope": "user",
                "unit_name": "myapp.container",
                "content": "[Container]\nImage=alpine\n",
            },
            follow_redirects=False,
        )
        assert response.status_code == 200

        async def _check():
            async with get_db_connection() as db:
                async with db.execute(
                    "SELECT server_id, file_path, scope, last_known_mtime, last_content_hash FROM quadlets WHERE server_id = 1 AND file_path = ?",
                    (file_path,)
                ) as cur:
                    return await cur.fetchall()

        rows = asyncio.run(_check())
        assert len(rows) == 1
        assert rows[0][3] is not None
        assert rows[0][4] is not None


@pytest.mark.unit
def test_save_quadlet_existing_file_bookkeeping(client):
    _setup_server()
    file_path = "/home/quadlet/.config/containers/systemd/myapp.container"

    async def _insert_existing():
        async with get_db_connection() as db:
            await db.execute(
                "INSERT INTO quadlets (server_id, file_path, scope, last_known_mtime, last_content_hash) VALUES (1, ?, 'user', 1000000000, 'oldhash')",
                (file_path,)
            )
            await db.commit()

    asyncio.run(_insert_existing())

    with patch("api.routes.write_remote_file", new_callable=AsyncMock), \
         patch("api.routes.pool.execute_command", new_callable=AsyncMock) as mock_exec, \
         patch("api.routes.quadlet_dir_for_scope", new_callable=AsyncMock) as mock_dir, \
         patch("api.routes.reload_and_restart", new_callable=AsyncMock):

        mock_exec.return_value = "1700000000"
        mock_dir.return_value = "/home/quadlet/.config/containers/systemd"

        content = "[Container]\nImage=alpine\n"
        expected_hash = hashlib.sha256(content.encode()).hexdigest()

        response = client.post(
            "/api/save",
            data={
                "server_id": 1,
                "file_path": file_path,
                "scope": "user",
                "unit_name": "myapp.container",
                "content": content,
            },
            follow_redirects=False,
        )
        assert response.status_code == 200

        async def _check():
            async with get_db_connection() as db:
                async with db.execute(
                    "SELECT server_id, file_path, scope, last_known_mtime, last_content_hash FROM quadlets WHERE server_id = 1"
                ) as cur:
                    return await cur.fetchall()

        rows = asyncio.run(_check())
        assert len(rows) == 1
        assert rows[0][1] == file_path
        assert rows[0][3] == 1700000000
        assert rows[0][4] == expected_hash


@pytest.mark.unit
def test_db_bookkeeping_failure_returns_success_toast(client):
    _setup_server()
    file_path = "/home/quadlet/.config/containers/systemd/myapp.container"

    @asynccontextmanager
    async def _mock_db_fail_on_write():
        class FailOnWriteDB:
            def execute(self, sql, *args, **kwargs):
                sql_upper = sql.strip().upper()
                if any(sql_upper.startswith(kw) for kw in ("INSERT", "UPDATE", "DELETE")):
                    raise Exception("DB Write Error")

                class MockCursor:
                    def __await__(self):
                        async def _res():
                            return self
                        return _res().__await__()

                    async def fetchone(self):
                        return ("[Container]\nImage=alpine\n",)

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                return MockCursor()

            async def commit(self):
                pass

        yield FailOnWriteDB()

    with patch("api.routes.write_remote_file", new_callable=AsyncMock), \
         patch("api.routes.pool.execute_command", new_callable=AsyncMock) as mock_exec, \
         patch("api.routes.quadlet_dir_for_scope", new_callable=AsyncMock) as mock_dir, \
         patch("api.routes.reload_and_restart", new_callable=AsyncMock), \
         patch("api.routes.get_db_connection", side_effect=_mock_db_fail_on_write):

        mock_exec.return_value = "1700000000"
        mock_dir.return_value = "/home/quadlet/.config/containers/systemd"

        # Test POST /api/create when DB write fails
        res_create = client.post(
            "/api/create",
            data={
                "server_id": 1,
                "scope": "user",
                "type": "container",
                "name": "myapp",
            },
            follow_redirects=False,
        )
        assert res_create.status_code == 200
        assert "Created" in res_create.text

        # Test POST /api/save when DB write fails
        res_save = client.post(
            "/api/save",
            data={
                "server_id": 1,
                "file_path": file_path,
                "scope": "user",
                "unit_name": "myapp.container",
                "content": "[Container]\nImage=alpine\n",
            },
            follow_redirects=False,
        )
        assert res_save.status_code == 200
        assert "Saved!" in res_save.text
