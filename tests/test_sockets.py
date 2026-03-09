import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi import WebSocket, WebSocketDisconnect
from api.sockets import ConnectionManager, stream_logs_over_websocket
from services.ssh_manager import pool

@pytest.fixture
def mock_websocket():
    ws = AsyncMock(spec=WebSocket)
    return ws

@pytest.mark.asyncio
async def test_connection_manager(mock_websocket):
    cm = ConnectionManager()
    await cm.connect(mock_websocket)
    assert mock_websocket in cm.active_connections
    mock_websocket.accept.assert_called_once()
    
    await cm.broadcast("test msg")
    mock_websocket.send_text.assert_called_with("test msg")
    
    cm.disconnect(mock_websocket)
    assert mock_websocket not in cm.active_connections

@pytest.mark.asyncio
async def test_stream_logs_over_websocket_disconnect(mock_websocket, monkeypatch):
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.terminate = MagicMock()
    
    async def mock_stdout():
        yield "log line 1\n"
        yield "log line 2\n"

    mock_process.stdout = mock_stdout()
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn
    
    monkeypatch.setattr("api.sockets.pool", mock_pool)
    
    mock_websocket.receive_text.side_effect = WebSocketDisconnect()
    
    await stream_logs_over_websocket(mock_websocket, server_id=1, unit_name="my_unit.service")
    
    mock_pool.get_connection.assert_called_once_with(1)
    mock_conn.create_process.assert_called_once_with("sudo journalctl -u my_unit.service -f -n 100")
    
    mock_process.terminate.assert_called_once()
    mock_process.wait.assert_awaited_once_with(check=False)

@pytest.mark.asyncio
async def test_stream_logs_over_websocket_stop_command(mock_websocket, monkeypatch):
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.terminate = MagicMock()
    
    async def empty_stdout():
        if False:
            yield ""
            
    mock_process.stdout = empty_stdout()
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn
    monkeypatch.setattr("api.sockets.pool", mock_pool)
    
    mock_websocket.receive_text.return_value = "STOP"
    
    await stream_logs_over_websocket(mock_websocket, server_id=1, unit_name="my_unit.service")
    
    mock_process.terminate.assert_called_once()
    mock_process.wait.assert_awaited_once_with(check=False)
