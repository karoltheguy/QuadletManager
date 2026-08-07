import asyncio
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


def _setup_server_and_quadlets():
    async def _init():
        async with get_db_connection() as db:
            await db.execute(
                "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (1, 's1', '10.0.0.1', 'root')"
            )
            await db.execute(
                "INSERT INTO quadlets (server_id, file_path, scope, last_known_mtime) VALUES (1, '/etc/containers/systemd/web.container', 'global', 1700000000)"
            )
            await db.execute(
                "INSERT INTO quadlets (server_id, file_path, scope, last_known_mtime) VALUES (1, '/home/quadlet/.config/containers/systemd/db.container', 'user', 1700000000)"
            )
            await db.commit()

    asyncio.run(_init())


def _setup_server_reconciled():
    async def _init():
        async with get_db_connection() as db:
            await db.execute(
                "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (1, 's1', '10.0.0.1', 'root')"
            )
            await db.execute(
                "UPDATE servers SET last_reconciled_at = 1700000000 WHERE id = 1"
            )
            await db.commit()

    asyncio.run(_init())


# 1. test: GET /api/quadlets/1 issues NO SSH commands
@pytest.mark.unit
def test_get_quadlet_tree_issues_no_ssh_commands(client):
    _setup_server()

    with patch("api.routes.pool.execute_command", new_callable=AsyncMock) as mock_exec, \
         patch("api.routes.fetch_all_quadlets", new_callable=AsyncMock) as mock_fetch:
        client.get("/api/quadlets/1")
        assert mock_exec.await_count == 0
        assert mock_fetch.await_count == 0


# 2. test: GET /api/quadlets/1 renders quadlets from database
@pytest.mark.unit
def test_get_quadlet_tree_renders_from_db(client):
    _setup_server_and_quadlets()

    with patch("api.routes.pool.execute_command", new_callable=AsyncMock) as mock_exec, \
         patch("api.routes.fetch_all_quadlets", new_callable=AsyncMock) as mock_fetch:
        response = client.get("/api/quadlets/1")
        assert response.status_code == 200
        assert "web.container" in response.text
        assert "db.container" in response.text
        assert "global Scope" in response.text
        assert "user Scope" in response.text
        assert mock_exec.await_count == 0
        assert mock_fetch.await_count == 0


# 3. test: server with NO quadlets and last_reconciled_at IS NULL renders "Not yet scanned"
@pytest.mark.unit
def test_get_quadlet_tree_unscanned_server(client):
    _setup_server()

    with patch("api.routes.pool.execute_command", new_callable=AsyncMock) as mock_exec, \
         patch("api.routes.fetch_all_quadlets", new_callable=AsyncMock) as mock_fetch:
        response = client.get("/api/quadlets/1")
        assert response.status_code == 200
        assert "Not yet scanned" in response.text


# 4. test: server with NO quadlets but non-NULL last_reconciled_at does NOT render "Not yet scanned"
@pytest.mark.unit
def test_get_quadlet_tree_empty_reconciled_server(client):
    _setup_server_reconciled()

    with patch("api.routes.pool.execute_command", new_callable=AsyncMock) as mock_exec, \
         patch("api.routes.fetch_all_quadlets", new_callable=AsyncMock) as mock_fetch:
        response = client.get("/api/quadlets/1")
        assert response.status_code == 200
        assert "Not yet scanned" not in response.text


# 5. test: reconcile_server_inventory publishes "quadlets_changed" when scan adds a file
@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.sync_engine.publisher.publish", new_callable=AsyncMock)
@patch("services.sync_engine._fetch_mtimes", new_callable=AsyncMock)
@patch("services.sync_engine.fetch_all_quadlets", create=True, new_callable=AsyncMock)
async def test_reconcile_publishes_quadlets_changed_on_inventory_change(
    mock_fetch_all, mock_fetch_mtimes, mock_publish
):
    from services.sync_engine import reconcile_server_inventory

    async with get_db_connection() as db:
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (1, 's1', '10.0.0.1', 'root')"
        )
        await db.commit()

    scan_data = {
        "global": [
            {"path": "/etc/containers/systemd/web.container", "name": "web.container", "scope": "global"}
        ],
        "user": [],
    }
    mock_fetch_all.return_value = scan_data
    mock_fetch_mtimes.return_value = {"/etc/containers/systemd/web.container": 1000}

    await reconcile_server_inventory(1, "global")

    mock_publish.assert_awaited_once_with("quadlets_changed", {"server_id": 1})

    mock_publish.reset_mock()

    await reconcile_server_inventory(1, "global")

    assert mock_publish.await_count == 0


# 6. test: polling_engine_loop calls reconcile_all_inventories BEFORE first asyncio.sleep
@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.sync_engine.check_quadlets", new_callable=AsyncMock)
@patch("services.sync_engine.reconcile_all_inventories", new_callable=AsyncMock)
@patch("services.sync_engine.asyncio.sleep", new_callable=AsyncMock)
async def test_polling_loop_runs_reconcile_before_first_sleep(
    mock_sleep, mock_reconcile, mock_check
):
    from services.sync_engine import polling_engine_loop

    order = []

    async def side_sleep(duration):
        order.append("sleep")
        raise asyncio.CancelledError()

    async def side_reconcile():
        order.append("reconcile")

    async def side_check():
        order.append("check")

    mock_sleep.side_effect = side_sleep
    mock_reconcile.side_effect = side_reconcile
    mock_check.side_effect = side_check

    await polling_engine_loop()

    assert len(order) > 0
    assert order[0] == "reconcile"
