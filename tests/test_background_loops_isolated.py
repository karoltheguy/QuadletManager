import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from core.database import get_db_connection
from main import app


def _setup_server():
    async def _init():
        async with get_db_connection() as db:
            await db.execute(
                "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (1, 's1', '10.0.0.1', 'root')"
            )
            await db.commit()

    asyncio.run(_init())


# test: background polling loop issues NO SSH commands during app startup/requests
@pytest.mark.unit
def test_background_loop_issues_no_ssh_commands():
    _setup_server()

    with patch("services.ssh_manager.pool.execute_command", new_callable=AsyncMock) as mock_exec, \
         patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as client:
            client.get("/api/servers")
            client.get("/api/servers")
            client.get("/api/servers")

        assert mock_exec.await_count == 0, (
            f"Expected zero SSH commands, but pool.execute_command was called "
            f"{mock_exec.await_count} time(s) with calls: {mock_exec.await_args_list}"
        )
