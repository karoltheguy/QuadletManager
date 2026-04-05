import asyncio
import logging
from typing import List
from fastapi import WebSocket, WebSocketDisconnect
from services.ssh_manager import pool

logger = logging.getLogger("quadlet-manager.sockets")

class ConnectionManager:
    def __init__(self):
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

async def stream_logs_over_websocket(websocket: WebSocket, server_id: int, unit_name: str, scope: str = "user"):
    await manager.connect(websocket)
    # Start journalctl process on remote server via ssh
    conn = await pool.get_connection(server_id)
    if scope == "global":
        cmd = f"sudo journalctl -u {unit_name} -f -n 100"
    else:
        cmd = f"journalctl --user -u {unit_name} -f -n 100"

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
    """
    Bidirectional WebSocket terminal for interactive podman exec.
    Supports terminal resize events and graceful cleanup on disconnect.
    """
    await manager.connect(websocket)
    logger.info(f"Starting terminal session for {container_name} on server {server_id}")

    conn = await pool.get_connection(server_id)
    process = None
    read_task = None

    try:
        # Start podman exec with PTY
        exec_cmd = f"podman exec -it {container_name} {cmd}"
        if scope == "global":
            exec_cmd = f"sudo {exec_cmd}"

        logger.debug(f"Executing: {exec_cmd}")
        process = await conn.create_process(
            exec_cmd,
            request_pty=True,
            term_type='xterm-256color'
        )

        # Background task to read stdout and send to client
        async def read_output():
            try:
                async for chunk in process.stdout:
                    try:
                        await websocket.send_text(chunk)
                    except Exception as e:
                        logger.debug(f"Failed to send to websocket: {e}")
                        break
            except Exception as e:
                logger.error(f"Error reading stdout: {e}")

        read_task = asyncio.create_task(read_output())

        # Main loop: receive input from client and send to stdin
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=300.0)

                if not data:
                    continue

                # Parse control messages (e.g., resize)
                if data.startswith('{'):
                    try:
                        import json
                        msg = json.loads(data)
                        if msg.get('type') == 'resize':
                            cols = msg.get('cols', 80)
                            rows = msg.get('rows', 24)
                            try:
                                process.set_terminal_size(cols, rows)
                                logger.debug(f"PTY resized to {cols}x{rows}")
                            except Exception as e:
                                logger.warning(f"Failed to resize PTY: {e}")
                        continue
                    except (json.JSONDecodeError, ValueError):
                        pass  # Not a control message, treat as input

                # Send input to stdin
                if process.stdin:
                    try:
                        process.stdin.write(data.encode())
                    except Exception as e:
                        logger.error(f"Failed to write to stdin: {e}")
                        break

            except asyncio.TimeoutError:
                logger.debug("Terminal receive timeout (expected periodically)")
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected for terminal {container_name}")
                break
            except Exception as e:
                logger.error(f"Terminal input error: {e}")
                break

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
