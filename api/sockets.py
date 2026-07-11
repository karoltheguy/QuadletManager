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
            except Exception as e:
                logger.error(f"Error broadcasting to socket: {e}")

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
            except Exception as e:
                logger.error(f"Error reading stdout: {e}")

        stdout_task = asyncio.create_task(read_stdout())

        while True:
            # Prevent the handler from closing, optionally handle client messages
            # If the client disconnects, a WebSocketDisconnect is raised
            data = await websocket.receive_text()
            if data == "STOP":
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {unit_name}")
    except Exception as e:
        logger.error(f"Log stream error: {e}")
    finally:
        manager.disconnect(websocket)
        logger.info(f"Killing remote journalctl for {unit_name}")
        if 'process' in locals():
            process.terminate()
            await process.wait(check=False)


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
    process_done = asyncio.Event()

    try:
        # Start podman exec with PTY (cmd is quoted to neutralize shell metacharacters)
        safe_cmd = shlex.quote(cmd)
        exec_cmd = f"podman exec -it {container_name} {safe_cmd}"
        if scope == "global":
            exec_cmd = f"sudo {exec_cmd}"

        logger.debug(f"Executing: {exec_cmd}")
        process = await conn.create_process(
            exec_cmd,
            request_pty=True,
            term_type='xterm-256color',
            encoding=None
        )

        # Background task to read stdout and send to client.
        # Use read() instead of "async for" (readline) — PTY prompts have no
        # trailing newline, so readline() blocks until the user types something,
        # producing a blank terminal screen (issue #100).
        async def read_output():
            try:
                while True:
                    chunk = await process.stdout.read(4096)
                    if not chunk:
                        break
                    try:
                        await websocket.send_bytes(chunk)
                    except Exception as e:
                        logger.debug(f"Failed to send to websocket: {e}")
                        break
            except Exception as e:
                logger.error(f"Error reading stdout: {e}")
            finally:
                process_done.set()

        async def write_input():
            try:
                while True:
                    data = await websocket.receive_text()
                    if not data:
                        continue

                    # Parse control messages (e.g., resize)
                    if data.startswith('{'):
                        try:
                            msg = json.loads(data)
                            if msg.get('type') == 'resize':
                                cols = msg.get('cols', 80)
                                rows = msg.get('rows', 24)
                                try:
                                    process.change_terminal_size(cols, rows)
                                    logger.debug(f"PTY resized to {cols}x{rows}")
                                except Exception as e:
                                    logger.warning(f"Failed to resize PTY: {e}")
                            continue
                        except (json.JSONDecodeError, ValueError):
                            pass  # Not a control message, treat as input

                    # Send input to stdin.
                    if process.stdin:
                        try:
                            process.stdin.write(data.encode())
                        except Exception as e:
                            logger.error(f"Failed to write to stdin: {e}")
                            break
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected for terminal {container_name}")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Terminal input error: {e}")

        read_task = asyncio.create_task(read_output())
        write_task = asyncio.create_task(write_input())

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
    except Exception as e:
        logger.error(f"Terminal session error: {e}")
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
