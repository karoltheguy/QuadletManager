"""Additional unit tests targeting previously uncovered branches in api/sockets.py.

Covers the global-scope command variants, streaming error handlers, terminal
input edge cases (empty data, malformed JSON control messages), and the
cleanup paths in the ``finally`` blocks.
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, call
from fastapi import WebSocket, WebSocketDisconnect

from api.sockets import stream_logs_over_websocket, exec_terminal_over_websocket


class _AsyncIter:
    """Minimal async iterator so ``async for chunk in process.stdout`` works."""

    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


@pytest.fixture
def mock_websocket():
    return AsyncMock(spec=WebSocket)


def _patch_pool(monkeypatch, conn):
    mock_pool = AsyncMock()
    mock_pool.get_connection.return_value = conn
    monkeypatch.setattr("api.sockets.pool", mock_pool)
    return mock_pool


# --------------------------------------------------------------------------
# stream_logs_over_websocket
# --------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.unit
async def test_stream_logs_global_scope_and_stdout_error(mock_websocket, monkeypatch):
    """scope='global' builds the sudo command and a failing send is handled."""
    mock_conn = AsyncMock()
    process = MagicMock()
    process.stdout = _AsyncIter([b"log chunk"])
    process.terminate = MagicMock()
    process.wait = AsyncMock()
    mock_conn.create_process = AsyncMock(return_value=process)
    _patch_pool(monkeypatch, mock_conn)

    # send_text raises when the read task forwards the chunk -> hits the
    # read_stdout except handler. The event lets the receive loop block until
    # the read task has actually reached (and failed) the send, avoiding a
    # timing-based sleep.
    send_attempted = asyncio.Event()

    def _send_text(_message):
        send_attempted.set()
        raise Exception("send failed")

    mock_websocket.send_text.side_effect = _send_text

    async def _receive():
        # Wait until the read task has attempted the send, then stop the loop.
        await send_attempted.wait()
        return "STOP"

    mock_websocket.receive_text.side_effect = _receive

    await stream_logs_over_websocket(
        mock_websocket, server_id=1, unit_name="my.service", scope="global"
    )

    # Global scope uses sudo journalctl
    called_cmd = mock_conn.create_process.call_args[0][0]
    assert called_cmd.startswith("sudo journalctl -u")
    process.terminate.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_stream_logs_generic_exception(mock_websocket, monkeypatch):
    """A non-disconnect error while starting the stream is caught and logged."""
    mock_conn = AsyncMock()
    mock_conn.create_process = AsyncMock(side_effect=RuntimeError("boom"))
    _patch_pool(monkeypatch, mock_conn)

    # Should not raise; the generic except handler swallows it.
    await stream_logs_over_websocket(
        mock_websocket, server_id=1, unit_name="my.service"
    )


# --------------------------------------------------------------------------
# exec_terminal_over_websocket
# --------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.unit
async def test_exec_terminal_invalid_name_send_error(mock_websocket, monkeypatch):
    """Invalid container name where the error notification also fails to send."""
    _patch_pool(monkeypatch, AsyncMock())
    mock_websocket.send_text.side_effect = Exception("send failed")

    await exec_terminal_over_websocket(
        mock_websocket, server_id=1, container_name="bad;name"
    )
    mock_websocket.send_text.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exec_terminal_global_scope_and_send_bytes_error(mock_websocket, monkeypatch):
    """scope='global' prefixes sudo; a failing send_bytes ends the read loop."""
    mock_conn = AsyncMock()
    process = MagicMock()
    process.stdout.read = AsyncMock(return_value=b"output")
    process.stdin = MagicMock()
    process.kill = MagicMock()
    process.wait = AsyncMock()
    mock_conn.create_process = AsyncMock(return_value=process)
    _patch_pool(monkeypatch, mock_conn)

    # Forwarding output fails -> read loop breaks and the process is marked done.
    mock_websocket.send_bytes.side_effect = Exception("send_bytes failed")
    # The "[process exited]" notification also fails -> exercises that except.
    mock_websocket.send_text.side_effect = Exception("send_text failed")

    async def _receive():
        # Keep the input task pending; it is cancelled once the read task ends.
        await asyncio.sleep(0.1)
        return "input"

    mock_websocket.receive_text.side_effect = _receive

    await exec_terminal_over_websocket(
        mock_websocket, server_id=1, container_name="ctr", scope="global"
    )

    exec_cmd = mock_conn.create_process.call_args[0][0]
    assert exec_cmd.startswith("sudo podman exec -it")
    process.kill.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exec_terminal_input_edge_cases(mock_websocket, monkeypatch):
    """Empty input is skipped, malformed JSON is treated as raw input,
    and an unexpected receive error is caught."""
    mock_conn = AsyncMock()
    process = MagicMock()

    async def _blocking_read(*_args, **_kwargs):
        # Stay pending while the write task processes its (synchronous) inputs
        # and raises; a short delay is enough to keep this task alive.
        await asyncio.sleep(0.1)
        return b""

    process.stdout.read = _blocking_read
    process.stdin = MagicMock()
    process.kill = MagicMock()
    process.wait = AsyncMock()
    mock_conn.create_process = AsyncMock(return_value=process)
    _patch_pool(monkeypatch, mock_conn)

    mock_websocket.receive_text.side_effect = [
        "",              # empty -> continue
        "{not json",     # starts with '{' but invalid -> treated as raw input
        "ls\n",          # normal input written to stdin
        RuntimeError("unexpected"),  # generic error handler
    ]

    await exec_terminal_over_websocket(
        mock_websocket, server_id=1, container_name="ctr"
    )

    # Empty input is skipped; malformed JSON and normal input are forwarded
    # verbatim (encoded) to stdin.
    assert process.stdin.write.call_args_list == [
        call(b"{not json"),
        call(b"ls\n"),
    ]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exec_terminal_cleanup_errors(mock_websocket, monkeypatch):
    """Exceptions raised by kill()/wait() during cleanup are swallowed."""
    mock_conn = AsyncMock()
    process = MagicMock()
    process.stdout.read = AsyncMock(return_value=b"")  # read loop ends immediately
    process.stdin = MagicMock()
    process.kill = MagicMock(side_effect=Exception("kill failed"))
    process.wait = AsyncMock(side_effect=Exception("wait failed"))
    mock_conn.create_process = AsyncMock(return_value=process)
    _patch_pool(monkeypatch, mock_conn)

    async def _receive():
        # Keep the input task pending; it is cancelled once the read task ends.
        await asyncio.sleep(0.1)
        return "input"

    mock_websocket.receive_text.side_effect = _receive

    # Should not raise despite kill()/wait() failing.
    await exec_terminal_over_websocket(
        mock_websocket, server_id=1, container_name="ctr"
    )
    process.kill.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exec_terminal_outer_websocket_disconnect(mock_websocket, monkeypatch):
    """A WebSocketDisconnect raised before the tasks start is handled."""
    mock_conn = AsyncMock()
    mock_conn.create_process = AsyncMock(side_effect=WebSocketDisconnect())
    _patch_pool(monkeypatch, mock_conn)

    await exec_terminal_over_websocket(
        mock_websocket, server_id=1, container_name="ctr"
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exec_terminal_outer_generic_exception(mock_websocket, monkeypatch):
    """A generic error raised while setting up the session is handled."""
    mock_conn = AsyncMock()
    mock_conn.create_process = AsyncMock(side_effect=RuntimeError("setup boom"))
    _patch_pool(monkeypatch, mock_conn)

    await exec_terminal_over_websocket(
        mock_websocket, server_id=1, container_name="ctr"
    )
