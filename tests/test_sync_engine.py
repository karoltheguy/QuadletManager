"""Tests for sync_engine module.

Migrated from unittest.IsolatedAsyncioTestCase to pytest-asyncio native style
to resolve event loop conflict (Issue #19).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.sync_engine import parse_mtime, check_quadlets


# =============================================================================
# TestParseMtime - async tests for parse_mtime()
# =============================================================================


@pytest.mark.asyncio
async def test_valid_timestamp():
    """Standard numeric timestamp string parses correctly."""
    result = await parse_mtime("1709827200\n")
    assert result == 1709827200


@pytest.mark.asyncio
async def test_timestamp_with_whitespace():
    """Timestamp padded with whitespace/newlines is trimmed and parsed."""
    result = await parse_mtime(" 1709827200 \n")
    assert result == 1709827200


@pytest.mark.asyncio
async def test_empty_string_returns_zero():
    """Empty string (e.g. file not found) falls back to 0."""
    result = await parse_mtime("")
    assert result == 0


@pytest.mark.asyncio
async def test_non_numeric_returns_zero():
    """Non-numeric output (e.g. stat error message) falls back to 0."""
    result = await parse_mtime("stat: cannot statx '/missing': No such file or directory")
    assert result == 0


@pytest.mark.asyncio
async def test_float_string_returns_zero():
    """Float-like string (e.g. '1709827200.5') cannot int-parse, falls back to 0."""
    result = await parse_mtime("1709827200.5")
    assert result == 0


@pytest.mark.asyncio
async def test_zero_timestamp():
    """Explicit zero is a valid mtime (epoch start)."""
    result = await parse_mtime("0")
    assert result == 0


# =============================================================================
# Helper functions for mocking
# =============================================================================


def _make_db_cm(quadlet_rows):
    """Build a single async context manager mock that satisfies:
    async with get_db_connection() as db:
        db.row_factory = ...
        async with db.execute(...) as cursor:
            rows = await cursor.fetchall()
    and also supports:
        await db.execute("UPDATE ...", (...))
        await db.commit()

    aiosqlite's db.execute() returns an object that is BOTH an async
    context manager (for SELECT) and awaitable (for UPDATE). We emulate
    this with a custom class.

    Returns (mock_db_cm, mock_db) — the CM is what get_db_connection()
    should return, and mock_db lets tests inspect calls.
    """
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=quadlet_rows)

    class DualProtocolCM:
        """Objects returned by aiosqlite execute() support both
        `async with obj` and `await obj`."""
        async def __aenter__(self):
            return mock_cursor

        async def __aexit__(self, *args):
            return False

        def __await__(self):
            async def _resolve():
                return mock_cursor
            return _resolve().__await__()

    mock_db = AsyncMock()
    mock_db.execute = MagicMock(return_value=DualProtocolCM())
    mock_db.commit = AsyncMock()

    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_db_cm, mock_db


# =============================================================================
# TestCheckQuadlets - async tests for check_quadlets()
# =============================================================================


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
async def test_newer_mtime_triggers_publish(mock_get_db_func, mock_pool, mock_publisher):
    """When the remote mtime is newer than the DB mtime, a file_changed event is published."""
    quadlet_row = {
        "id": 1,
        "server_id": 10,
        "file_path": "/etc/containers/systemd/web.container",
        "scope": "global",
        "last_known_mtime": 1000,
    }

    # check_quadlets calls get_db_connection() twice: once for SELECT, once for UPDATE.
    select_cm, _ = _make_db_cm([quadlet_row])
    update_cm, _ = _make_db_cm([])

    mock_get_db_func.side_effect = [select_cm, update_cm]

    # stat returns a newer mtime, cat returns content
    mock_pool.execute_command = AsyncMock(side_effect=["2000\n", "[Container]\nImage=nginx\n"])
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    # Should have published a file_changed event
    mock_publisher.publish.assert_called_once()
    call_args = mock_publisher.publish.call_args[0]
    assert call_args[0] == "file_changed"
    assert call_args[1]["server_id"] == 10
    assert call_args[1]["file_path"] == "/etc/containers/systemd/web.container"
    assert "message" in call_args[1]


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
async def test_same_mtime_no_publish(mock_get_db_func, mock_pool, mock_publisher):
    """When the remote mtime matches the DB mtime, no event is published."""
    quadlet_row = {
        "id": 2,
        "server_id": 10,
        "file_path": "/etc/containers/systemd/db.container",
        "scope": "global",
        "last_known_mtime": 1500,
    }

    select_cm, _ = _make_db_cm([quadlet_row])
    mock_get_db_func.side_effect = [select_cm]

    # stat returns the same mtime as the DB
    mock_pool.execute_command = AsyncMock(return_value="1500\n")
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    mock_publisher.publish.assert_not_called()


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
async def test_older_mtime_no_publish(mock_get_db_func, mock_pool, mock_publisher):
    """When the remote mtime is *older* than the DB mtime (edge case), no event fires."""
    quadlet_row = {
        "id": 3,
        "server_id": 10,
        "file_path": "/etc/containers/systemd/old.container",
        "scope": "global",
        "last_known_mtime": 2000,
    }

    select_cm, _ = _make_db_cm([quadlet_row])
    mock_get_db_func.side_effect = [select_cm]

    mock_pool.execute_command = AsyncMock(return_value="1000\n")
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    mock_publisher.publish.assert_not_called()


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
async def test_none_mtime_no_publish(mock_get_db_func, mock_pool, mock_publisher):
    """When last_known_mtime is None (newly registered, never polled), no event fires."""
    quadlet_row = {
        "id": 4,
        "server_id": 10,
        "file_path": "/etc/containers/systemd/new.container",
        "scope": "user",
        "last_known_mtime": None,
    }

    select_cm, _ = _make_db_cm([quadlet_row])
    mock_get_db_func.side_effect = [select_cm]

    mock_pool.execute_command = AsyncMock(return_value="5000\n")
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    # None mtime means we haven't baselined yet, so no "changed" event
    mock_publisher.publish.assert_not_called()


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
async def test_ssh_error_does_not_crash(mock_get_db_func, mock_pool, mock_publisher):
    """If SSH fails for a quadlet, the function logs the error but doesn't raise."""
    quadlet_row = {
        "id": 5,
        "server_id": 99,
        "file_path": "/etc/containers/systemd/broken.container",
        "scope": "global",
        "last_known_mtime": 1000,
    }

    select_cm, _ = _make_db_cm([quadlet_row])
    mock_get_db_func.side_effect = [select_cm]

    mock_pool.execute_command = AsyncMock(side_effect=ConnectionError("SSH timeout"))
    mock_publisher.publish = AsyncMock()

    # Should NOT raise
    await check_quadlets()

    mock_publisher.publish.assert_not_called()


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
async def test_user_scope_does_not_use_sudo(mock_get_db_func, mock_pool, mock_publisher):
    """User-scope quadlets should use use_sudo=False."""
    quadlet_row = {
        "id": 6,
        "server_id": 10,
        "file_path": "~/.config/containers/systemd/app.container",
        "scope": "user",
        "last_known_mtime": 1000,
    }

    select_cm, _ = _make_db_cm([quadlet_row])
    mock_get_db_func.side_effect = [select_cm]

    mock_pool.execute_command = AsyncMock(return_value="1000\n")
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    # Verify the stat command was called with use_sudo=False
    mock_pool.execute_command.assert_called_once_with(
        10,
        "stat -c %Y ~/.config/containers/systemd/app.container",
        use_sudo=False,
    )


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
async def test_global_scope_uses_sudo(mock_get_db_func, mock_pool, mock_publisher):
    """Global-scope quadlets should use use_sudo=True."""
    quadlet_row = {
        "id": 7,
        "server_id": 10,
        "file_path": "/etc/containers/systemd/sys.container",
        "scope": "global",
        "last_known_mtime": 1000,
    }

    select_cm, _ = _make_db_cm([quadlet_row])
    mock_get_db_func.side_effect = [select_cm]

    mock_pool.execute_command = AsyncMock(return_value="1000\n")
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    mock_pool.execute_command.assert_called_once_with(
        10,
        "stat -c %Y /etc/containers/systemd/sys.container",
        use_sudo=True,
    )


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
async def test_no_quadlets_in_db_is_noop(mock_get_db_func, mock_pool, mock_publisher):
    """When the quadlets table is empty, nothing happens."""
    select_cm, _ = _make_db_cm([])
    mock_get_db_func.side_effect = [select_cm]

    mock_pool.execute_command = AsyncMock()
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    mock_pool.execute_command.assert_not_called()
    mock_publisher.publish.assert_not_called()


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
async def test_db_updated_with_new_mtime(mock_get_db_func, mock_pool, mock_publisher):
    """After detecting a change, the DB is updated with the new remote mtime."""
    quadlet_row = {
        "id": 8,
        "server_id": 10,
        "file_path": "/etc/containers/systemd/cache.container",
        "scope": "global",
        "last_known_mtime": 1000,
    }

    select_cm, _ = _make_db_cm([quadlet_row])
    update_cm, update_db = _make_db_cm([])
    mock_get_db_func.side_effect = [select_cm, update_cm]

    mock_pool.execute_command = AsyncMock(side_effect=["3000\n", "[Container]\nImage=redis\n"])
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    # Verify that the UPDATE SQL was called on the second DB connection
    update_db.execute.assert_called()
    update_call = update_db.execute.call_args
    sql = update_call[0][0]
    params = update_call[0][1]
    assert "UPDATE quadlets SET last_known_mtime" in sql
    assert params == (3000, 8)
    update_db.commit.assert_called_once()


# =============================================================================
# TestCollisionAvoidance - tests for collision avoidance logic
# =============================================================================


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
async def test_after_save_updates_mtime_no_false_positive(mock_get_db_func, mock_pool, mock_publisher):
    """Simulates: UI saves at mtime=2000, poller sees mtime=2000 → no event.

    If the /api/save endpoint correctly updates last_known_mtime after writing,
    the next poll cycle will see matching mtimes and stay silent.
    """
    # DB already has the updated mtime from the save endpoint
    quadlet_row = {
        "id": 10,
        "server_id": 10,
        "file_path": "/etc/containers/systemd/web.container",
        "scope": "global",
        "last_known_mtime": 2000,  # Updated by the save endpoint
    }

    select_cm, _ = _make_db_cm([quadlet_row])
    mock_get_db_func.side_effect = [select_cm]

    # Remote file has the same mtime=2000 (our own write)
    mock_pool.execute_command = AsyncMock(return_value="2000\n")
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    # No false-positive "file changed externally" event
    mock_publisher.publish.assert_not_called()

@pytest.mark.asyncio
async def test_polling_engine_loop_cancelled():
    import asyncio
    from services.sync_engine import polling_engine_loop
    with patch("services.sync_engine.asyncio.sleep", side_effect=asyncio.CancelledError()):
        await polling_engine_loop()

@pytest.mark.asyncio
async def test_polling_engine_loop_exception_caught():
    import asyncio
    from services.sync_engine import polling_engine_loop
    count = 0
    async def mock_sleep(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise asyncio.CancelledError()
            
    with patch("services.sync_engine.asyncio.sleep", side_effect=mock_sleep), \
         patch("services.sync_engine.check_quadlets", side_effect=Exception("sync error")):
        await polling_engine_loop()
