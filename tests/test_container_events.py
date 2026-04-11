"""Tests for container events logging and retrieval."""
import pytest
import time
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from core.database import get_db_connection, init_db


@pytest.fixture
def test_db(monkeypatch):
    """Create and initialize a test database with container_events table."""
    # Create a temporary database file
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Patch DATABASE_PATH before importing
    monkeypatch.setenv("QUADLET_DB_PATH", db_path)

    # Initialize the database with all tables
    import asyncio
    asyncio.run(init_db())

    # Clear container_events before yielding
    async def clear_events():
        from core.database import get_db_connection
        async with get_db_connection() as db:
            await db.execute("DELETE FROM container_events")
            await db.commit()

    asyncio.run(clear_events())

    yield db_path

    # Cleanup
    os.unlink(db_path)


@pytest.mark.asyncio
async def test_record_container_event(test_db):
    """Test recording a container event."""
    from services.container_events import record_container_event

    server_id = 1
    container_name = "nginx"
    event_type = "start"
    triggered_by = "admin"
    details = "Container started manually"

    await record_container_event(server_id, container_name, event_type, triggered_by, details)

    # Verify event was recorded
    async with get_db_connection() as db:
        async with db.execute(
            "SELECT server_id, container_name, event_type, triggered_by, details FROM container_events WHERE container_name = ?",
            (container_name,)
        ) as cursor:
            row = await cursor.fetchone()

    assert row is not None
    assert row[0] == server_id
    assert row[1] == container_name
    assert row[2] == event_type
    assert row[3] == triggered_by
    assert row[4] == details


@pytest.mark.asyncio
async def test_get_container_activity(test_db):
    """Test fetching container activity events."""
    from services.container_events import record_container_event, get_container_activity

    server_id = 1
    container_name = "redis"

    # Record multiple events
    for i, action in enumerate(["start", "stop", "restart"]):
        await record_container_event(server_id, container_name, action, "admin", f"Event {i}")
        await record_container_event(server_id, "other-container", "start", "admin", "Other event")

    # Fetch activity for specific container
    events = await get_container_activity(server_id, container_name, limit=10)

    # Should only get events for the specific container, in reverse chronological order
    assert len(events) == 3
    assert all(event["container_name"] == container_name for event in events)
    assert events[0]["event_type"] == "restart"  # Most recent first
    assert events[1]["event_type"] == "stop"
    assert events[2]["event_type"] == "start"


@pytest.mark.asyncio
async def test_get_container_activity_respects_limit(test_db):
    """Test that activity retrieval respects the limit parameter."""
    from services.container_events import record_container_event, get_container_activity

    server_id = 1
    container_name = "postgres"

    # Record 15 events
    for i in range(15):
        await record_container_event(server_id, container_name, "start", "admin", f"Event {i}")

    # Request only 5
    events = await get_container_activity(server_id, container_name, limit=5)

    assert len(events) == 5


@pytest.mark.asyncio
async def test_activity_event_includes_timestamp(test_db):
    """Test that activity events include readable timestamps."""
    from services.container_events import record_container_event, get_container_activity

    server_id = 1
    container_name = "app"

    before = int(time.time())
    await record_container_event(server_id, container_name, "start", "editor", "")
    after = int(time.time())

    events = await get_container_activity(server_id, container_name, limit=1)

    assert len(events) == 1
    assert "occurred_at" in events[0]
    assert before <= events[0]["occurred_at"] <= after


@pytest.mark.asyncio
async def test_cleanup_old_events_removes_old_records(test_db):
    """Test that cleanup_old_events deletes records older than the retention period."""
    from services.container_events import record_container_event, cleanup_old_events

    server_id = 1
    container_name = "old-container"
    retention_days = 30
    old_timestamp = int(time.time()) - (retention_days * 86400) - 3600  # 1 hour past cutoff

    # Insert an old event directly with a past timestamp
    async with get_db_connection() as db:
        await db.execute(
            "INSERT INTO container_events (server_id, container_name, event_type, occurred_at) VALUES (?, ?, ?, ?)",
            (server_id, container_name, "stop", old_timestamp)
        )
        await db.commit()

    await cleanup_old_events(retention_days=retention_days)

    async with get_db_connection() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM container_events WHERE container_name = ?",
            (container_name,)
        ) as cursor:
            count = (await cursor.fetchone())[0]

    assert count == 0, f"Expected old events to be deleted, but found {count}"


@pytest.mark.asyncio
async def test_cleanup_old_events_preserves_recent_records(test_db):
    """Test that cleanup_old_events does not delete recent records."""
    from services.container_events import record_container_event, cleanup_old_events

    server_id = 1
    container_name = "recent-container"

    await record_container_event(server_id, container_name, "start", "admin", "Recent event")

    await cleanup_old_events(retention_days=30)

    async with get_db_connection() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM container_events WHERE container_name = ?",
            (container_name,)
        ) as cursor:
            count = (await cursor.fetchone())[0]

    assert count == 1, f"Expected recent event to be preserved, but found {count}"


@pytest.mark.asyncio
async def test_cleanup_old_events_mixed(test_db):
    """Test that cleanup deletes only old events and keeps recent ones."""
    from services.container_events import record_container_event, cleanup_old_events

    server_id = 1
    retention_days = 30
    old_timestamp = int(time.time()) - (retention_days * 86400) - 3600

    # Insert one old and one recent event
    async with get_db_connection() as db:
        await db.execute(
            "INSERT INTO container_events (server_id, container_name, event_type, occurred_at) VALUES (?, ?, ?, ?)",
            (server_id, "old-box", "failure", old_timestamp)
        )
        await db.commit()

    await record_container_event(server_id, "recent-box", "start", "admin", "")

    await cleanup_old_events(retention_days=retention_days)

    async with get_db_connection() as db:
        async with db.execute("SELECT container_name FROM container_events") as cursor:
            remaining = [row[0] for row in await cursor.fetchall()]

    assert "old-box" not in remaining
    assert "recent-box" in remaining


@pytest.mark.asyncio
async def test_get_activity_route_caps_limit():
    """Test that the /api/activity route caps an unbounded client-supplied limit at 100."""
    from unittest.mock import AsyncMock, patch

    captured_limit = {}

    async def fake_get_container_activity(server_id, container, limit=10):
        captured_limit["value"] = limit
        return []

    with patch("api.routes.get_container_activity", side_effect=fake_get_container_activity):
        from api.routes import get_activity
        result = await get_activity(server_id=1, container="nginx", limit=999999, role="viewer")

    assert captured_limit["value"] <= 100, (
        f"Expected limit to be capped at 100, but got {captured_limit['value']}"
    )
