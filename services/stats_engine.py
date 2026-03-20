import asyncio
import json
import logging
from core.database import get_db_connection
from services.ssh_manager import pool
from core.events_manager import publisher

logger = logging.getLogger("quadlet-manager.stats")

STATS_INTERVAL_SEC = 5
PODMAN_PS_TIMEOUT = 5   # seconds – `podman ps` is near-instant; fail fast if Podman is frozen
STATS_CMD_TIMEOUT = 15  # seconds – --no-stream should return quickly

# Rootless podman over non-interactive SSH needs XDG_RUNTIME_DIR so it can
# locate the user session (socket, cgroup delegates, etc.).  Without this
# the command either hangs or silently returns nothing.
ROOTLESS_ENV_PREFIX = 'XDG_RUNTIME_DIR=/run/user/$(id -u)'


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


async def _fetch_scope_stats(server_id: int, rootful: bool) -> list[dict]:
    """Fetch container stats for one scope (rootful or rootless).

    Returns a list of normalised container dicts, or an empty list on error.
    """
    if rootful:
        ps_cmd = 'sudo podman ps --format "{{.Names}}"'
        stats_prefix = "sudo podman stats"
    else:
        ps_cmd = f'{ROOTLESS_ENV_PREFIX} podman ps --format "{{{{.Names}}}}"'
        stats_prefix = f"{ROOTLESS_ENV_PREFIX} podman stats"

    try:
        running_str = await pool.execute_command(
            server_id, ps_cmd, timeout=PODMAN_PS_TIMEOUT,
        )
        running_names = running_str.strip().split() if running_str.strip() else []
        if not running_names:
            return []

        names_arg = " ".join(running_names)
        cmd = f"{stats_prefix} --no-stream --format json {names_arg}"
        stats_json_str = await pool.execute_command(
            server_id, cmd, timeout=STATS_CMD_TIMEOUT,
        )

        if not stats_json_str.strip():
            return []

        stats_data = json.loads(stats_json_str)
        return [normalize_container_stats(c) for c in stats_data]

    except Exception as e:
        scope_label = "global" if rootful else "user"
        logger.warning(
            f"Could not fetch {scope_label}-scope stats for server {server_id}: {e}"
        )
        return []


async def fetch_server_stats():
    """Polls all registered servers for Podman stats and pushes via SSE."""
    async with get_db_connection() as db:
        async with db.execute("SELECT id, name FROM servers") as cursor:
            servers = await cursor.fetchall()

    for server in servers:
        server_id = server[0]
        server_name = server[1]
        try:
            # Fetch both rootless (user) and rootful (global) containers,
            # then merge into a single update so the frontend shows all.
            user_containers, global_containers = await asyncio.gather(
                _fetch_scope_stats(server_id, rootful=False),
                _fetch_scope_stats(server_id, rootful=True),
            )

            containers = user_containers + global_containers

            await publisher.publish("stats_update", {
                "server_id": server_id,
                "server_name": server_name,
                "containers": containers,
            })

        except Exception as e:
            logger.error(f"Error polling stats for server {server_id} ({server_name}): {e}")
            # Publish an error event so the frontend can show feedback
            # instead of forever displaying "Waiting for stats data..."
            await publisher.publish("stats_error", {
                "server_id": server_id,
                "server_name": server_name,
                "error": str(e),
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
