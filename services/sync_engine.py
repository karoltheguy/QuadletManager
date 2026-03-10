import asyncio
import logging
from core.database import get_db_connection
from services.ssh_manager import pool
from core.events_manager import publisher

logger = logging.getLogger("quadlet-manager.sync")

POLL_INTERVAL_SEC = 10

async def parse_mtime(stdout: str) -> int:
    try:
        return int(stdout.strip())
    except ValueError:
        return 0

async def check_quadlets():
    """Polls all registered quadlets to see if the remote file has been modified."""
    async with get_db_connection() as db:
        db.row_factory = lambda cursor, row: {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
        async with db.execute("SELECT id, server_id, file_path, scope, last_known_mtime FROM quadlets") as cursor:
            quadlets = await cursor.fetchall()
            
    for q in quadlets:
        try:
            use_sudo = (q['scope'] == 'global')
            stat_cmd = f"stat -c %Y {q['file_path']}"
            
            # Fetch remote mtime
            mtime_str = await pool.execute_command(q['server_id'], stat_cmd, use_sudo=use_sudo)
            remote_mtime = await parse_mtime(mtime_str)
            
            # If the remote is newer than the DB timestamp
            if q['last_known_mtime'] is not None and remote_mtime > q['last_known_mtime']:
                logger.warning(f"File {q['file_path']} on server {q['server_id']} was modified externally!")
                
                # Fetch new content
                cat_cmd = f"cat {q['file_path']}"
                new_content = await pool.execute_command(q['server_id'], cat_cmd, use_sudo=use_sudo)
                
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
