import asyncio
import json
import logging
import re
import shlex
from typing import List
from fastapi import WebSocket, WebSocketDisconnect
from services.ssh_manager import pool

logger = logging.getLogger("quadlet-manager.sockets")

# Allowlist for systemd unit names (supports template instances like foo@bar.service)
_UNIT_NAME_RE = re.compile(r"^[a-zA-Z0-9_@\-\.:\\]+$")
# Allowlist for podman container names/ids
_CONTAINER_NAME_RE = re.compile(r"^[a-zA-Z0-9_\.\-]+$")

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

async def stream_logs_over_websocket(websocket: WebSocket, server_id: int, unit_name: str, scope: str = "user", since: str = None):
    await manager.connect(websocket)
    if not _UNIT_NAME_RE.match(unit_name or ""):
        logger.warning(f"Rejected invalid unit_name: {unit_name!r}")
        try:
            await websocket.send_text("error: invalid unit name")
        except Exception:
            pass
        manager.disconnect(websocket)
        return
    safe_unit = shlex.quote(unit_name)
    # Start journalctl process on remote server via ssh
    conn = await pool.get_connection(server_id)
    since_phrase = _SINCE_PHRASES.get(since)
    if since_phrase is not None:
        tail_clause = f"--since {shlex.quote(since_phrase)}"
    else:
        tail_clause = "-n 100"
    if scope == "global":
        cmd = f"sudo journalctl -u {safe_unit} -f {tail_clause}"
    else:
        cmd = f"journalctl --user -u {safe_unit} -f {tail_clause}"

    logger.info(f"Starting log stream for {unit_name} on server {server_id}")

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
        logger.info(f"WebSocket disconnected for {unit_name}")
    except Exception:
        logger.exception("Log stream error")
    finally:
        manager.disconnect(websocket)
        logger.info(f"Killing remote journalctl for {unit_name}")
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
            logger.debug(f"PTY resized to {cols}x{rows}")
        except Exception as e:
            logger.warning(f"Failed to resize PTY: {e}")
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
                    logger.debug(f"Failed to send to websocket: {e}")
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
            logger.info(f"WebSocket disconnected for terminal {self.container_name}")
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Terminal input error")


async def exec_terminal_over_websocket(websocket: WebSocket, server_id: int, container_name: str, scope: str = "user", cmd: str = "bash"):
    """Bidirectional WebSocket terminal for interactive podman exec.

    Supports terminal resize events and graceful cleanup on disconnect.
    """
    await manager.connect(websocket)
    logger.info(f"Starting terminal session for {container_name} on server {server_id}")

    if not _CONTAINER_NAME_RE.match(container_name or ""):
        logger.warning(f"Rejected invalid container_name: {container_name!r}")
        try:
            await websocket.send_text("error: invalid container name")
        except Exception:
            pass
        manager.disconnect(websocket)
        return

    conn = await pool.get_connection(server_id)
    process = None
    read_task = None

    try:
        exec_cmd = _build_exec_command(container_name, cmd, scope)
        logger.debug(f"Executing: {exec_cmd}")
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
            logger.info(f"Process exited for terminal {container_name}, notifying client")
            try:
                await websocket.send_text('\r\n\x1b[33m[process exited]\x1b[0m\r\n')
            except Exception:
                pass

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for terminal {container_name}")
    except Exception:
        logger.exception("Terminal session error")
    finally:
        manager.disconnect(websocket)
        logger.info(f"Closing terminal session for {container_name}")
        if read_task:
            try:
                read_task.cancel()
            except Exception:
                pass
        if process:
            try:
                process.kill()
            except Exception:
                pass
            try:
                await process.wait(check=False)
            except Exception:
                pass
