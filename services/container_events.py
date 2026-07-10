"""Container events recording and retrieval."""
import asyncio
import os
import time
from core.database import get_db_connection
import logging

logger = logging.getLogger("quadlet-manager.container_events")

EVENTS_RETENTION_DAYS = int(os.environ.get("QUADLET_EVENTS_RETENTION_DAYS", "30"))
CLEANUP_INTERVAL_SEC = 86400  # run once per day


async def record_container_event(
    server_id: int,
    container_name: str,
    event_type: str,
    triggered_by: str | None = None,
    details: str | None = None
) -> None:
    """Record a container lifecycle event to the database.

    :param server_id: The server ID.
    :param container_name: The container name.
    :param event_type: One of 'start', 'stop', 'restart', 'failure'.
    :param triggered_by: Username or 'system'. Defaults to None.
    :param details: Optional details about the event. Defaults to None.
    """
    occurred_at = int(time.time())

    async with get_db_connection() as db:
        await db.execute(
            """INSERT INTO container_events
            (server_id, container_name, event_type, triggered_by, details, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (server_id, container_name, event_type, triggered_by, details, occurred_at)
        )
        await db.commit()

    logger.info(f"Recorded event {event_type} for {container_name} on server {server_id}")


async def get_container_activity(
    server_id: int,
    container_name: str,
    limit: int = 10
) -> list[dict]:
    """Fetch recent activity events for a specific container.

    :param server_id: The server ID.
    :param container_name: The container name.
    :param limit: Maximum number of events to return. Defaults to 10.
    :return: List of dicts with event details, most recent first.
    """
    async with get_db_connection() as db:
        async with db.execute(
            """SELECT id, server_id, container_name, event_type, triggered_by, details, occurred_at
            FROM container_events
            WHERE server_id = ? AND container_name = ?
            ORDER BY occurred_at DESC
            LIMIT ?""",
            (server_id, container_name, limit)
        ) as cursor:
            rows = await cursor.fetchall()

    return [
        {
            "id": row[0],
            "server_id": row[1],
            "container_name": row[2],
            "event_type": row[3],
            "triggered_by": row[4],
            "details": row[5],
            "occurred_at": row[6],
        }
        for row in rows
    ]


async def cleanup_old_events(retention_days: int = EVENTS_RETENTION_DAYS) -> int:
    """Delete container events older than retention_days. Returns the number of deleted rows."""
    cutoff = int(time.time()) - (retention_days * 86400)
    async with get_db_connection() as db:
        cursor = await db.execute(
            "DELETE FROM container_events WHERE occurred_at < ?", (cutoff,)
        )
        deleted = cursor.rowcount
        await db.commit()
    if deleted:
        logger.info(f"Pruned {deleted} container event(s) older than {retention_days} days.")
    return deleted


async def container_events_cleanup_loop():
    logger.info(f"Starting container events cleanup task (retention={EVENTS_RETENTION_DAYS}d, interval={CLEANUP_INTERVAL_SEC}s).")
    try:
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL_SEC)
            try:
                await cleanup_old_events()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Container events cleanup error: {e}")
    except asyncio.CancelledError:
        logger.info("Container events cleanup stopped.")
