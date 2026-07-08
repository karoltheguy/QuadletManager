"""Additional unit tests targeting previously uncovered branches in
services/ssh_manager.py: the sudo prefix, timeout cleanup failures,
cancellation propagation, and reconnect close failures.
"""
import asyncio

import asyncssh
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.ssh_manager import SSHConnectionPool


@pytest.fixture
def pool():
    return SSHConnectionPool()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_execute_command_uses_sudo(pool):
    """use_sudo=True prepends 'sudo ' to the command."""
    mock_conn = AsyncMock()
    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=("ok", ""))
    mock_process.exit_status = 0
    mock_conn.create_process.return_value = mock_process

    with patch.object(pool, "get_connection", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_conn
        res = await pool.execute_command(1, "systemctl status foo", use_sudo=True)

    assert res == "ok"
    assert mock_conn.create_process.call_args[0][0] == "sudo systemctl status foo"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_timeout_cleanup_errors_are_swallowed(pool):
    """When the command times out, kill()/close() failures are ignored and a
    timeout error is raised."""
    mock_conn = AsyncMock()
    mock_process = MagicMock()

    async def _slow_communicate():
        await asyncio.sleep(0.1)
        return ("", "")

    mock_process.communicate = _slow_communicate
    mock_process.kill = MagicMock(side_effect=Exception("kill failed"))
    mock_process.close = MagicMock(side_effect=Exception("close failed"))
    mock_conn.create_process.return_value = mock_process

    with patch.object(pool, "get_connection", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_conn
        with pytest.raises(Exception, match="Command timed out"):
            await pool.execute_command(1, "sleep 10", timeout=0.01)

    mock_process.kill.assert_called_once()
    mock_process.close.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_cancelled_error_propagates(pool):
    """A CancelledError during communicate is re-raised after cleanup."""
    mock_conn = AsyncMock()
    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(side_effect=asyncio.CancelledError())
    mock_process.kill = MagicMock()
    mock_process.close = MagicMock()
    mock_conn.create_process.return_value = mock_process

    with patch.object(pool, "get_connection", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_conn
        with pytest.raises(asyncio.CancelledError):
            await pool.execute_command(1, "ls", timeout=5)

    mock_process.kill.assert_called_once()
    mock_process.close.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_reconnect_swallows_close_error(pool):
    """During reconnect the stale connection's close() error is ignored."""
    stale_conn = MagicMock()
    stale_conn._transport.is_closing.return_value = False
    stale_conn.create_process = AsyncMock(
        side_effect=asyncssh.ChannelOpenError(1, "channel refused")
    )
    stale_conn.close.side_effect = Exception("close failed")

    fresh_conn = AsyncMock()
    fresh_process = MagicMock()
    fresh_process.communicate = AsyncMock(return_value=("recovered", ""))
    fresh_process.exit_status = 0
    fresh_conn.create_process.return_value = fresh_process

    pool.connections[1] = stale_conn

    with patch.object(pool, "connect_to_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = fresh_conn
        res = await pool.execute_command(1, "ls")

    assert res == "recovered"
    stale_conn.close.assert_called_once()
