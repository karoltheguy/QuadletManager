import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import WebSocket, WebSocketDisconnect
from api.sockets import ConnectionManager, stream_logs_over_websocket, exec_terminal_over_websocket

@pytest.fixture
def mock_websocket():
    ws = AsyncMock(spec=WebSocket)
    return ws

@pytest.mark.asyncio
@pytest.mark.unit
async def test_connection_manager_broadcast_error(mock_websocket):
    cm = ConnectionManager()
    await cm.connect(mock_websocket)
    
    mock_websocket.send_text.side_effect = Exception("Broadcast Error")
    
    # Should catch and log error, not raise
    await cm.broadcast("test message")

@pytest.mark.asyncio
@pytest.mark.unit
async def test_stream_logs_invalid_unit_name_send_error(mock_websocket, monkeypatch):
    mock_websocket.send_text.side_effect = Exception("Send Error")
    
    # Should catch error when sending "error: invalid unit name"
    await stream_logs_over_websocket(mock_websocket, server_id=1, unit_name="invalid;")
    mock_websocket.send_text.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.unit
async def test_exec_terminal_resize_error(mock_websocket, monkeypatch):
    import json
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.change_terminal_size = MagicMock(side_effect=Exception("Resize Error"))
    mock_process.kill = MagicMock()
    mock_process.stdin = MagicMock()
    mock_process.stdout.read = AsyncMock(side_effect=[b""])
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn
    monkeypatch.setattr("api.sockets.pool", mock_pool)
    
    resize_event = json.dumps({"type": "resize", "cols": 120, "rows": 40})
    mock_websocket.receive_text.side_effect = [resize_event, WebSocketDisconnect()]
    
    await exec_terminal_over_websocket(mock_websocket, server_id=1, container_name="test")

@pytest.mark.asyncio
@pytest.mark.unit
async def test_exec_terminal_input_error(mock_websocket, monkeypatch):
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.kill = MagicMock()
    mock_stdin = MagicMock()
    mock_stdin.write.side_effect = Exception("Write Error")
    mock_process.stdin = mock_stdin
    mock_process.stdout.read = AsyncMock(side_effect=[b""])
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn
    monkeypatch.setattr("api.sockets.pool", mock_pool)
    
    mock_websocket.receive_text.side_effect = ["ls\n", WebSocketDisconnect()]
    
    await exec_terminal_over_websocket(mock_websocket, server_id=1, container_name="test")

@pytest.mark.asyncio
@pytest.mark.unit
async def test_exec_terminal_stdout_read_error(mock_websocket, monkeypatch):
    import asyncio
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.kill = MagicMock()
    mock_process.stdin = MagicMock()
    mock_process.stdout.read = AsyncMock(side_effect=Exception("Read Error"))
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn
    monkeypatch.setattr("api.sockets.pool", mock_pool)
    
    async def mock_receive():
        await asyncio.sleep(0.1) # Wait for stdout task to hit error
        raise WebSocketDisconnect()
        
    mock_websocket.receive_text.side_effect = mock_receive
    
    await exec_terminal_over_websocket(mock_websocket, server_id=1, container_name="test")
