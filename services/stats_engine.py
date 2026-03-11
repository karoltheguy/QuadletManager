import asyncio
import json
import logging
from core.database import get_db_connection
from services.ssh_manager import pool
from core.events_manager import publisher

logger = logging.getLogger("quadlet-manager.stats")

STATS_INTERVAL_SEC = 5
STATS_CMD_TIMEOUT = 15  # seconds – --no-stream should return quickly


def normalize_container_stats(raw: dict) -> dict:
    """Normalize podman stats JSON keys across different Podman versions."""
    return {
        "name": raw.get("name") or raw.get("Name", "unknown"),
        "cpu": raw.get("cpu_percent") or raw.get("CPUPerc") or raw.get("CPU", "0%"),
        "mem": raw.get("mem_percent") or raw.get("MemPerc") or raw.get("Mem", "0%"),
        "mem_usage": raw.get("mem_usage") or raw.get("MemUsage", "—"),
        "net_io": raw.get("net_io") or raw.get("NetIO", "—"),
        "block_io": raw.get("block_io") or raw.get("BlockIO", "—"),
        "pids": raw.get("pids") or raw.get("PIDs", "0"),
    }


async def fetch_server_stats():
    """Polls all registered servers for Podman stats and pushes via SSE."""
    async with get_db_connection() as db:
        async with db.execute("SELECT id, name FROM servers") as cursor:
            servers = await cursor.fetchall()

    for server in servers:
        server_id = server[0]
        server_name = server[1]
        try:
            # We fetch podman stats as JSON with a tight timeout.
            # podman stats --no-stream returns immediately on a healthy system,
            # but can hang indefinitely if podman's internal DB is locked
            # (e.g. by a stuck pod rm/create operation).
            cmd = "podman stats --no-stream --format json"
            stats_json_str = await pool.execute_command(
                server_id, cmd, timeout=STATS_CMD_TIMEOUT
            )

            if not stats_json_str.strip():
                # No containers running — push empty update
                await publisher.publish("stats_update", {
                    "server_id": server_id,
                    "server_name": server_name,
                    "containers": []
                })
                continue

            stats_data = json.loads(stats_json_str)

            # Normalize across Podman versions for a stable frontend contract
            containers = [normalize_container_stats(c) for c in stats_data]

            await publisher.publish("stats_update", {
                "server_id": server_id,
                "server_name": server_name,
                "containers": containers
            })

        except Exception as e:
            logger.error(f"Error polling stats for server {server_id} ({server_name}): {e}")
            # Publish an error event so the frontend can show feedback
            # instead of forever displaying "Waiting for stats data..."
            await publisher.publish("stats_error", {
                "server_id": server_id,
                "server_name": server_name,
                "error": str(e)
            })


async def stats_engine_loop():
    logger.info("Starting Resource Stats polling background task.")
    try:
        while True:
            await asyncio.sleep(STATS_INTERVAL_SEC)
            try:
                await fetch_server_stats()
            except asyncio.CancelledError:
                raise  # Re-raise to exit the loop
            except Exception as e:
                logger.error(f"Stats engine error: {e}")
    except asyncio.CancelledError:
        logger.info("Stats engine stopped.")
