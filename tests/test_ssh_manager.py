import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from services.ssh_manager import SSHConnectionPool, SSHCommandError, SSHTimeoutError
import asyncssh
from contextlib import asynccontextmanager

@pytest.fixture
def pool():
    return SSHConnectionPool()

@pytest.fixture
def mock_db_ctx():
    @asynccontextmanager
    async def _mock_db():
        db_mock = AsyncMock()
        cursor_mock = AsyncMock()
        cursor_mock.fetchone.return_value = ("127.0.0.1:22", "user", "enc", None)
        
        @asynccontextmanager
        async def _mock_execute(*args, **kwargs):
            yield cursor_mock
            
        db_mock.execute = _mock_execute
        yield db_mock
    return _mock_db

@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_connection_caches(pool, mock_db_ctx):
    with patch("services.ssh_manager.get_db_connection", side_effect=mock_db_ctx), \
         patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect, \
         patch("services.ssh_manager.decrypt_private_key", return_value="dummy_key"), \
         patch("asyncssh.import_private_key"):
        
        mock_conn = MagicMock()
        mock_conn._transport.is_closing.return_value = False
        # No host key observed (GSS-style) so the TOFU path skips persisting;
        # pinning behaviour is covered in test_host_key_pinning.py.
        mock_conn.get_server_host_key.return_value = None
        mock_connect.return_value = mock_conn

        conn1 = await pool.get_connection(1)
        conn2 = await pool.get_connection(1)

        assert conn1 is conn2
        assert mock_connect.call_count == 1

@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_connection_reconnects_if_closed(pool):
    pool.connections[1] = MagicMock()
    pool.connections[1]._transport.is_closing.return_value = True

    with patch.object(pool, "connect_to_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = "new_conn"
        conn = await pool.get_connection(1)
        assert conn == "new_conn"

@pytest.mark.asyncio
@pytest.mark.unit
async def test_execute_command_success(pool):
    mock_conn = AsyncMock()
    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=("output", ""))
    mock_process.exit_status = 0
    mock_conn.create_process.return_value = mock_process

    with patch.object(pool, "get_connection", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_conn
        res = await pool.execute_command(1, "ls")
        assert res == "output"

@pytest.mark.asyncio
@pytest.mark.unit
async def test_execute_command_process_error(pool):
    mock_conn = AsyncMock()
    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=("", "error"))
    mock_process.exit_status = 1
    mock_conn.create_process.return_value = mock_process

    with patch.object(pool, "get_connection", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_conn
        with pytest.raises(SSHCommandError, match="Command execution failed: error") as exc_info:
            await pool.execute_command(1, "ls")
        assert exc_info.value.exit_status == 1
        assert exc_info.value.stderr == "error"

@pytest.mark.asyncio
@pytest.mark.unit
async def test_execute_command_timeout(pool):
    mock_conn = AsyncMock()
    mock_process = MagicMock()
    async def slow_communicate():
        await asyncio.sleep(0.1)
        return ("", "")
    mock_process.communicate = slow_communicate
    mock_conn.create_process.return_value = mock_process

    with patch.object(pool, "get_connection", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_conn
        with pytest.raises(SSHTimeoutError, match="Command timed out"):
            await pool.execute_command(1, "ls", timeout=0.01)
        mock_process.kill.assert_called_once()
        mock_process.close.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.unit
async def test_execute_command_reconnects_on_channel_error(pool):
    mock_conn1 = MagicMock()
    mock_conn1._transport.is_closing.return_value = False
    mock_conn1.create_process = AsyncMock(side_effect=asyncssh.ChannelOpenError(1, "fail"))
    
    mock_conn2 = AsyncMock()
    mock_process2 = MagicMock()
    mock_process2.communicate = AsyncMock(return_value=("success", ""))
    mock_process2.exit_status = 0
    mock_conn2.create_process.return_value = mock_process2

    pool.connections[1] = mock_conn1
    
    with patch.object(pool, "connect_to_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_conn2
        
        res = await pool.execute_command(1, "ls")
        assert res == "success"
        mock_conn1.close.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.unit
async def test_execute_command_reconnects_on_disconnect(pool):
    mock_conn1 = MagicMock()
    mock_conn1._transport.is_closing.return_value = False
    mock_conn1.create_process = AsyncMock(side_effect=asyncssh.ConnectionLost("lost"))
    
    mock_conn2 = AsyncMock()
    mock_process2 = MagicMock()
    mock_process2.communicate = AsyncMock(return_value=("success", ""))
    mock_process2.exit_status = 0
    mock_conn2.create_process.return_value = mock_process2

    pool.connections[1] = mock_conn1
    
    with patch.object(pool, "connect_to_server", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_conn2
        
        res = await pool.execute_command(1, "ls")
        assert res == "success"
        mock_conn1.close.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.unit
async def test_close_all(pool):
    mock_conn1 = MagicMock()
    mock_conn2 = MagicMock()
    pool.connections = {1: mock_conn1, 2: mock_conn2}
    await pool.close_all()
    mock_conn1.close.assert_called_once()
    mock_conn2.close.assert_called_once()
    assert len(pool.connections) == 0

@pytest.mark.asyncio
@pytest.mark.unit
async def test_connect_to_server_not_found(pool):
    @asynccontextmanager
    async def _mock_db_empty():
        db_mock = AsyncMock()
        cursor_mock = AsyncMock()
        cursor_mock.fetchone.return_value = None
        @asynccontextmanager
        async def _mock_execute(*args, **kwargs):
            yield cursor_mock
        db_mock.execute = _mock_execute
        yield db_mock

    with patch("services.ssh_manager.get_db_connection", side_effect=_mock_db_empty):
        with pytest.raises(Exception, match="Server 1 not found"):
            await pool.connect_to_server(1)

@pytest.mark.asyncio
@pytest.mark.unit
async def test_connect_to_server_invalid_key(pool, mock_db_ctx):
    with patch("services.ssh_manager.get_db_connection", side_effect=mock_db_ctx), \
         patch("services.ssh_manager.decrypt_private_key", side_effect=ValueError("bad key")):
        
        with pytest.raises(Exception, match="Failed to decrypt SSH key"):
            await pool.connect_to_server(1)
