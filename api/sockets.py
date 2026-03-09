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

async def stream_logs_over_websocket(websocket: WebSocket, server_id: int, unit_name: str):
    await manager.connect(websocket)
    # Start journalctl process on remote server via ssh
    conn = await pool.get_connection(server_id)
    cmd = f"sudo journalctl -u {unit_name} -f -n 100"
    
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
