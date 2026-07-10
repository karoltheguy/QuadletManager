import asyncio
import logging
import shlex
from core.database import get_db_connection
from services.ssh_manager import pool
from services.remote_fs import is_global_scope
from core.events_manager import publisher

logger = logging.getLogger("quadlet-manager.sync")

POLL_INTERVAL_SEC = 10

async def parse_mtime(stdout: str) -> int:
    try:
        return int(stdout.strip())
    except ValueError:
        return 0

def _quote_remote_path(path: str) -> str:
    """Quote a remote path for safe shell use while preserving a leading ~/
    so the remote shell still performs tilde (home directory) expansion."""
    if path.startswith("~/"):
        return "~/" + shlex.quote(path[2:])
    return shlex.quote(path)

async def _fetch_mtimes(server_id, use_sudo, paths) -> dict[str, int]:
    """Fetch mtimes for multiple remote paths on the same server/scope in a
    single SSH round-trip, mapping the stat output back to the caller's
    (possibly tilde-prefixed) DB paths."""
    quoted = [_quote_remote_path(p) for p in paths]
    cmd = "stat -c '%n %Y' " + " ".join(quoted) + " 2>/dev/null; true"

    output = await pool.execute_command(server_id, cmd, use_sudo=use_sudo)

    printed = {}
    for line in (output or "").splitlines():
        if not line.strip():
            continue
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            continue
        printed_path, mtime_str = parts
        try:
            mtime = int(mtime_str)
        except ValueError:
            continue
        printed[printed_path] = mtime

    result = {}
    for p in paths:
        if p in printed:
            result[p] = printed[p]
        elif p.startswith("~"):
            suffix = p[1:]
            for printed_path, mtime in printed.items():
                if printed_path.endswith(suffix):
                    result[p] = mtime
                    break
    return result


async def check_quadlets():
    """Polls all registered quadlets to see if the remote file has been modified."""
    async with get_db_connection() as db:
        db.row_factory = lambda cursor, row: {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
        async with db.execute("SELECT id, server_id, file_path, scope, last_known_mtime FROM quadlets") as cursor:
            quadlets = await cursor.fetchall()

    groups = {}
    for q in quadlets:
        key = (q['server_id'], is_global_scope(q['scope']))
        groups.setdefault(key, []).append(q)

    group_keys = list(groups.keys())
    tasks = [
        _fetch_mtimes(server_id, use_sudo, [q['file_path'] for q in groups[(server_id, use_sudo)]])
        for (server_id, use_sudo) in group_keys
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for (server_id, use_sudo), result in zip(group_keys, results):
        rows = groups[(server_id, use_sudo)]

        if isinstance(result, Exception):
            logger.error(f"Error polling server {server_id} (use_sudo={use_sudo}): {result}")
            continue

        for q in rows:
            try:
                if q['file_path'] not in result:
                    continue

                remote_mtime = result[q['file_path']]

                # If the remote is newer than the DB timestamp
                if q['last_known_mtime'] is not None and remote_mtime > q['last_known_mtime']:
                    logger.warning(f"File {q['file_path']} on server {q['server_id']} was modified externally!")

                    # Emit Server-Sent Event broadcast (SSE)
                    await publisher.publish("file_changed", {
                        "server_id": q['server_id'],
                        "file_path": q['file_path'],
                        "message": "File modified externally!"
                    })

                    async with get_db_connection() as db:
                        await db.execute(
                            "UPDATE quadlets SET last_known_mtime = ? WHERE id = ?",
                            (remote_mtime, q['id'])
                        )
                        await db.commit()

            except Exception as e:
                logger.error(f"Error polling quadlet {q['id']}: {e}")

async def polling_engine_loop():
    logger.info("Starting Timestamp Polling background task.")
    try:
        while True:
            await asyncio.sleep(POLL_INTERVAL_SEC)
            try:
                await check_quadlets()
            except asyncio.CancelledError:
                raise  # Re-raise to exit the loop
            except Exception as e:
                logger.error(f"Polling engine error: {e}")
    except asyncio.CancelledError:
        logger.info("Polling engine stopped.")
