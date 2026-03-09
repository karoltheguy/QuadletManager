import asyncio
import json
import logging
from core.database import get_db_connection
from services.ssh_manager import pool

logger = logging.getLogger("quadlet-manager.stats")

STATS_INTERVAL_SEC = 5

async def fetch_server_stats():
    """Polls all registered servers for Podman stats."""
    async with await get_db_connection() as db:
        async with db.execute("SELECT id FROM servers") as cursor:
            servers = await cursor.fetchall()
            
    for (server_id,) in servers:
        try:
            # We fetch podman stats as JSON
            cmd = "podman stats --no-stream --format json"
            stats_json_str = await pool.execute_command(server_id, cmd)
            
            if not stats_json_str.strip():
                continue
                
            stats_data = json.loads(stats_json_str)
            
            # TODO: Emit to WebSocket for the frontend Inspector panel
            # e.g.: await manager.broadcast(json.dumps({"type": "stats", "server_id": server_id, "data": stats_data}))
            
        except Exception as e:
            logger.error(f"Error polling stats for server {server_id}: {e}")

async def stats_engine_loop():
    logger.info("Starting Resource Stats polling background task.")
    while True:
        await asyncio.sleep(STATS_INTERVAL_SEC)
        try:
            await fetch_server_stats()
        except Exception as e:
            logger.error(f"Stats engine error: {e}")
