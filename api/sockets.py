import asyncio
import json
import logging
import re
import shlex
from typing import List
from fastapi import WebSocket, WebSocketDisconnect
from services.ssh_manager import pool

logger = logging.getLogger("quadlet-manager.sockets")

# Allowlist for systemd unit names (supports template instances like foo@bar.service).
# \Z rather than $ so a trailing newline is not accepted.
_UNIT_NAME_RE = re.compile(r"^[a-zA-Z0-9_@\-\.:\\]+\Z")
# Allowlist for podman container names/ids
_CONTAINER_NAME_RE = re.compile(r"^[a-zA-Z0-9_\.\-]+\Z")


def _log_safe(value) -> str:
    """Escape control characters in a client-supplied value before logging it.

    Newlines, carriage returns and ANSI escapes would otherwise let a caller
    forge extra log lines. Escaping rather than stripping keeps the original
    bytes visible for debugging.
    """
    return str(value).encode("unicode_escape").decode("ascii")

class ConnectionManager:
    def __init__(self):
        """Initialize the ConnectionManager with an empty connections list."""
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                logger.exception("Error broadcasting to socket")

manager = ConnectionManager()

# Allowlist mapping range codes to journalctl --since phrases. Values are
# never taken from user input directly, so this is the only source of
# --since text interpolated into the shell command.
_SINCE_PHRASES = {
    "5m": "5 minutes ago",
    "15m": "15 minutes ago",
    "1h": "1 hour ago",
    "6h": "6 hours ago",
    "24h": "24 hours ago",
}


async def _reject_invalid_name(websocket: WebSocket, value: str, pattern, field_label: str, error_text: str) -> bool:
    """Reject and close the socket when `value` fails `pattern`.

    Returns True when the request was rejected and the caller must return.
    """
    if pattern.match(value or ""):
        return False
    logger.warning(f"Rejected invalid {field_label}: {_log_safe(value)}")
    try:
        await websocket.send_text(error_text)
    except Exception as exc:  # noqa: BLE001 - best-effort notify; the disconnect below must still run
        logger.debug(f"Could not notify client of invalid {field_label}: {_log_safe(exc)}")
    manager.disconnect(websocket)
    return True


def _build_journalctl_command(unit_name: str, scope: str, since: str | None) -> str:
    safe_unit = shlex.quote(unit_name)
    since_phrase = _SINCE_PHRASES.get(since) if since else None
    if since_phrase is not None:
        tail_clause = f"--since {shlex.quote(since_phrase)}"
    else:
        tail_clause = "-n 100"
    if scope == "global":
        return f"sudo journalctl -u {safe_unit} -f {tail_clause}"
    return f"journalctl --user -u {safe_unit} -f {tail_clause}"


async def stream_logs_over_websocket(websocket: WebSocket, server_id: int, unit_name: str, scope: str = "user", since: str | None = None):
    await manager.connect(websocket)
    if await _reject_invalid_name(websocket, unit_name, _UNIT_NAME_RE, "unit_name", "error: invalid unit name"):
        return
    # Start journalctl process on remote server via ssh
    conn = await pool.get_connection(server_id)
    cmd = _build_journalctl_command(unit_name, scope, since)

    logger.info(f"Starting log stream for {_log_safe(unit_name)} on server {server_id}")

    # We use create_process to stream standard output
    try:
        process = await conn.create_process(cmd)

        # Background task to send data from stdout to websocket
        async def read_stdout():
            try:
                async for chunk in process.stdout:
                    await websocket.send_text(chunk)
            except Exception:
                logger.exception("Error reading stdout")

        stdout_task = asyncio.create_task(read_stdout())

        while True:
            # Prevent the handler from closing, optionally handle client messages
            # If the client disconnects, a WebSocketDisconnect is raised
            data = await websocket.receive_text()
            if data == "STOP":
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {_log_safe(unit_name)}")
    except Exception:
        logger.exception("Log stream error")
    finally:
        manager.disconnect(websocket)
        logger.info(f"Killing remote journalctl for {_log_safe(unit_name)}")
        if 'process' in locals():
            process.terminate()
            await process.wait(check=False)


def _build_exec_command(container_name: str, cmd: str, scope: str) -> str:
    """Build the podman exec command for a PTY session (cmd is quoted to
    neutralize shell metacharacters)."""
    safe_cmd = shlex.quote(cmd)
    exec_cmd = f"podman exec -it {container_name} {safe_cmd}"
    if scope == "global":
        exec_cmd = f"sudo {exec_cmd}"
    return exec_cmd


async def _cleanup_terminal(read_task, process) -> None:
    """Cancel the read task and kill the remote process, swallowing any
    cleanup errors so they never mask the original error."""
    if read_task:
        try:
            read_task.cancel()
        except Exception as exc:  # noqa: BLE001 - teardown must not mask the original error
            logger.debug(f"Failed to cancel terminal read task: {_log_safe(exc)}")
    if process:
        try:
            process.kill()
        except Exception as exc:  # noqa: BLE001 - teardown must not mask the original error
            logger.debug(f"Failed to kill remote process: {_log_safe(exc)}")
        try:
            await process.wait(check=False)
        except Exception as exc:  # noqa: BLE001 - teardown must not mask the original error
            logger.debug(f"Failed to reap remote process: {_log_safe(exc)}")


def _try_handle_control_message(data: str, process) -> bool:
    """Parse `data` as a control message (e.g. resize) if it looks like JSON.

    Returns True if `data` was a control message and has been handled,
    meaning the caller should not forward it to the process stdin.
    """
    if not data.startswith('{'):
        return False
    try:
        msg = json.loads(data)
    except (json.JSONDecodeError, ValueError):
        return False
    if msg.get('type') == 'resize':
        cols, rows = msg.get('cols', 80), msg.get('rows', 24)
        try:
            process.change_terminal_size(cols, rows)
            logger.debug(f"PTY resized to {_log_safe(cols)}x{_log_safe(rows)}")
        except Exception as e:
            logger.warning(f"Failed to resize PTY: {_log_safe(e)}")
    return True


class TerminalSession:
    """Holds the live state for one interactive podman-exec PTY session."""

    def __init__(self, process, websocket: WebSocket, container_name: str):
        self.process = process
        self.websocket = websocket
        self.container_name = container_name
        self.process_done = asyncio.Event()

    async def read_output(self):
        # Use read() instead of "async for" (readline) — PTY prompts have no
        # trailing newline, so readline() blocks until the user types something,
        # producing a blank terminal screen (issue #100).
        try:
            while True:
                chunk = await self.process.stdout.read(4096)
                if not chunk:
                    break
                try:
                    await self.websocket.send_bytes(chunk)
                except Exception as e:
                    logger.debug(f"Failed to send to websocket: {_log_safe(e)}")
                    break
        except Exception:
            logger.exception("Error reading stdout")
        finally:
            self.process_done.set()

    async def write_input(self):
        try:
            while True:
                data = await self.websocket.receive_text()
                if not data or _try_handle_control_message(data, self.process):
                    continue

                if self.process.stdin:
                    try:
                        self.process.stdin.write(data.encode())
                    except Exception:
                        logger.exception("Failed to write to stdin")
                        break
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for terminal {_log_safe(self.container_name)}")
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Terminal input error")


async def exec_terminal_over_websocket(websocket: WebSocket, server_id: int, container_name: str, scope: str = "user", cmd: str = "bash"):
    """Bidirectional WebSocket terminal for interactive podman exec.

    Supports terminal resize events and graceful cleanup on disconnect.
    """
    await manager.connect(websocket)
    if await _reject_invalid_name(websocket, container_name, _CONTAINER_NAME_RE, "container_name", "error: invalid container name"):
        return

    logger.info(f"Starting terminal session for {_log_safe(container_name)} on server {server_id}")

    conn = await pool.get_connection(server_id)
    process = None
    read_task = None

    try:
        exec_cmd = _build_exec_command(container_name, cmd, scope)
        logger.debug(f"Executing: {_log_safe(exec_cmd)}")
        process = await conn.create_process(
            exec_cmd,
            request_pty=True,
            term_type='xterm-256color',
            encoding=None
        )

        session = TerminalSession(process, websocket, container_name)
        read_task = asyncio.create_task(session.read_output())
        write_task = asyncio.create_task(session.write_input())

        done, pending = await asyncio.wait(
            [read_task, write_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

        if read_task in done:
            logger.info(f"Process exited for terminal {_log_safe(container_name)}, notifying client")
            try:
                await websocket.send_text('\r\n\x1b[33m[process exited]\x1b[0m\r\n')
            except Exception:
                pass

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for terminal {_log_safe(container_name)}")
    except Exception:
        logger.exception("Terminal session error")
    finally:
        manager.disconnect(websocket)
        logger.info(f"Closing terminal session for {_log_safe(container_name)}")
        await _cleanup_terminal(read_task, process)
