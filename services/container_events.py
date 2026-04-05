"""Container events recording and retrieval."""
import time
from core.database import get_db_connection
import logging

logger = logging.getLogger("quadlet-manager.container_events")


async def record_container_event(
    server_id: int,
    container_name: str,
    event_type: str,
    triggered_by: str | None = None,
    details: str | None = None
) -> None:
    """Record a container lifecycle event to the database.

    Args:
        server_id: The server ID
        container_name: The container name
        event_type: One of 'start', 'stop', 'restart', 'failure'
        triggered_by: Username or 'system'
        details: Optional details about the event
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

    Args:
        server_id: The server ID
        container_name: The container name
        limit: Maximum number of events to return

    Returns:
        List of dicts with event details, most recent first
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
