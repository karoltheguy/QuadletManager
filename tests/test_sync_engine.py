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
@pytest.mark.unit
async def test_valid_timestamp():
    """Standard numeric timestamp string parses correctly."""
    result = await parse_mtime("1709827200\n")
    assert result == 1709827200


@pytest.mark.asyncio
@pytest.mark.unit
async def test_timestamp_with_whitespace():
    """Timestamp padded with whitespace/newlines is trimmed and parsed."""
    result = await parse_mtime(" 1709827200 \n")
    assert result == 1709827200


@pytest.mark.asyncio
@pytest.mark.unit
async def test_empty_string_returns_zero():
    """Empty string (e.g. file not found) falls back to 0."""
    result = await parse_mtime("")
    assert result == 0


@pytest.mark.asyncio
@pytest.mark.unit
async def test_non_numeric_returns_zero():
    """Non-numeric output (e.g. stat error message) falls back to 0."""
    result = await parse_mtime("stat: cannot statx '/missing': No such file or directory")
    assert result == 0


@pytest.mark.asyncio
@pytest.mark.unit
async def test_float_string_returns_zero():
    """Float-like string (e.g. '1709827200.5') cannot int-parse, falls back to 0."""
    result = await parse_mtime("1709827200.5")
    assert result == 0


@pytest.mark.asyncio
@pytest.mark.unit
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
@pytest.mark.unit
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
    mock_pool.execute_command = AsyncMock(side_effect=["/etc/containers/systemd/web.container 2000\n", "[Container]\nImage=nginx\n"])
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
@pytest.mark.unit
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
    mock_pool.execute_command = AsyncMock(return_value="/etc/containers/systemd/db.container 1500\n")
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    mock_publisher.publish.assert_not_called()


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
@pytest.mark.unit
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

    mock_pool.execute_command = AsyncMock(return_value="/etc/containers/systemd/old.container 1000\n")
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    mock_publisher.publish.assert_not_called()


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
@pytest.mark.unit
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

    mock_pool.execute_command = AsyncMock(return_value="/etc/containers/systemd/new.container 5000\n")
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    # None mtime means we haven't baselined yet, so no "changed" event
    mock_publisher.publish.assert_not_called()


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
@pytest.mark.unit
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
@pytest.mark.unit
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

    mock_pool.execute_command = AsyncMock(return_value="~/.config/containers/systemd/app.container 1000\n")
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    # Verify the stat command was called with use_sudo=False
    mock_pool.execute_command.assert_called_once_with(
        10,
        "stat -c '%n %Y' ~/.config/containers/systemd/app.container 2>/dev/null; true",
        use_sudo=False,
    )


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
@pytest.mark.unit
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

    mock_pool.execute_command = AsyncMock(return_value="/etc/containers/systemd/sys.container 1000\n")
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    mock_pool.execute_command.assert_called_once_with(
        10,
        "stat -c '%n %Y' /etc/containers/systemd/sys.container 2>/dev/null; true",
        use_sudo=True,
    )


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
@pytest.mark.unit
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
@pytest.mark.unit
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

    mock_pool.execute_command = AsyncMock(side_effect=["/etc/containers/systemd/cache.container 3000\n", "[Container]\nImage=redis\n"])
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
@pytest.mark.unit
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
    mock_pool.execute_command = AsyncMock(return_value="/etc/containers/systemd/web.container 2000\n")
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    # No false-positive "file changed externally" event
    mock_publisher.publish.assert_not_called()

@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
@pytest.mark.unit
async def test_batched_stat_one_call_per_server_scope_group(mock_get_db_func, mock_pool, mock_publisher):
    """Quadlets sharing (server_id, use_sudo) should be batched into a single
    stat command instead of one SSH round-trip per file."""
    quadlet_rows = [
        {
            "id": 1,
            "server_id": 10,
            "file_path": "/etc/containers/systemd/a.container",
            "scope": "global",
            "last_known_mtime": 1000,
        },
        {
            "id": 2,
            "server_id": 10,
            "file_path": "/etc/containers/systemd/b.container",
            "scope": "global",
            "last_known_mtime": 1000,
        },
        {
            "id": 3,
            "server_id": 10,
            "file_path": "/home/u/c.container",
            "scope": "user",
            "last_known_mtime": 1000,
        },
    ]

    select_cm, _ = _make_db_cm(quadlet_rows)
    update_cm, _ = _make_db_cm([])
    mock_get_db_func.side_effect = [select_cm, update_cm]

    async def fake_execute_command(server_id, cmd, use_sudo=False):
        if "a.container" in cmd and "b.container" in cmd:
            return "/etc/containers/systemd/a.container 2000\n/etc/containers/systemd/b.container 1000\n"
        if "c.container" in cmd:
            return "/home/u/c.container 1000\n"
        raise AssertionError(f"Unexpected command: {cmd}")

    mock_pool.execute_command = AsyncMock(side_effect=fake_execute_command)
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    # Exactly one batched call per (server_id, use_sudo) group, not per-file.
    assert mock_pool.execute_command.call_count == 2

    global_call = next(
        c for c in mock_pool.execute_command.call_args_list if c.kwargs.get("use_sudo") is True
    )
    user_call = next(
        c for c in mock_pool.execute_command.call_args_list if c.kwargs.get("use_sudo") is False
    )

    global_cmd = global_call.args[1]
    assert "stat -c '%n %Y'" in global_cmd
    assert "/etc/containers/systemd/a.container" in global_cmd
    assert "/etc/containers/systemd/b.container" in global_cmd

    user_cmd = user_call.args[1]
    assert "/home/u/c.container" in user_cmd

    # Only a.container changed (2000 > 1000); b.container and c.container are unchanged.
    mock_publisher.publish.assert_called_once()
    call_args = mock_publisher.publish.call_args[0]
    assert call_args[0] == "file_changed"
    assert call_args[1]["file_path"] == "/etc/containers/systemd/a.container"


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
@pytest.mark.unit
async def test_batched_stat_tilde_path_mapped_by_suffix(mock_get_db_func, mock_pool, mock_publisher):
    """stat prints the shell-expanded absolute path for a ~/ quadlet path, so the
    batched result must be mapped back to the DB's tilde path by suffix match."""
    quadlet_row = {
        "id": 5,
        "server_id": 10,
        "file_path": "~/.config/containers/systemd/app.container",
        "scope": "user",
        "last_known_mtime": 1000,
    }

    select_cm, _ = _make_db_cm([quadlet_row])
    update_cm, update_db = _make_db_cm([])
    mock_get_db_func.side_effect = [select_cm, update_cm]

    mock_pool.execute_command = AsyncMock(
        return_value="/home/carol/.config/containers/systemd/app.container 2000\n"
    )
    mock_publisher.publish = AsyncMock()

    await check_quadlets()

    mock_publisher.publish.assert_called_once()
    call_args = mock_publisher.publish.call_args[0]
    assert call_args[0] == "file_changed"
    assert call_args[1]["file_path"] == "~/.config/containers/systemd/app.container"

    update_db.execute.assert_called()
    update_call = update_db.execute.call_args
    params = update_call[0][1]
    assert params == (2000, 5)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_polling_engine_loop_cancelled():
    import asyncio
    from services.sync_engine import polling_engine_loop
    with patch("services.sync_engine.asyncio.sleep", side_effect=asyncio.CancelledError()):
        await polling_engine_loop()

@pytest.mark.asyncio
@pytest.mark.unit
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


# =============================================================================
# TestPollHealthTracker - pure logic tests for PollHealthTracker (issue #184)
# =============================================================================


@pytest.mark.unit
def test_module_constants_exist():
    """Sanity check the health instrumentation thresholds are defined."""
    from services.sync_engine import (
        SLOW_FETCH_THRESHOLD_SEC,
        CONSECUTIVE_FAILURES_THRESHOLD,
        CYCLE_BUDGET_RATIO,
    )
    assert SLOW_FETCH_THRESHOLD_SEC == 5
    assert CONSECUTIVE_FAILURES_THRESHOLD == 3
    assert CYCLE_BUDGET_RATIO == 0.8


@pytest.mark.unit
def test_module_level_health_tracker_instance_exists():
    """A module-level `health_tracker` singleton must be importable."""
    from services.sync_engine import health_tracker, PollHealthTracker
    assert isinstance(health_tracker, PollHealthTracker)


@pytest.mark.unit
def test_first_and_second_consecutive_failure_no_event():
    """1st and 2nd consecutive failures for a server produce no event."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    assert tracker.record_fetch(server_id=1, duration=0.1, success=False) is None
    assert tracker.record_fetch(server_id=1, duration=0.1, success=False) is None


@pytest.mark.unit
def test_third_consecutive_failure_fires_unhealthy_event():
    """3rd consecutive failure transitions the server to unhealthy."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    tracker.record_fetch(server_id=1, duration=0.1, success=False)
    tracker.record_fetch(server_id=1, duration=0.1, success=False)
    event = tracker.record_fetch(server_id=1, duration=0.1, success=False)

    assert event == {
        "scope": "server",
        "server_id": 1,
        "healthy": False,
        "reason": "consecutive_failures",
        "consecutive_failures": 3,
        "last_duration": 0.1,
    }


@pytest.mark.unit
def test_fourth_and_beyond_failure_no_event_already_unhealthy():
    """4th and subsequent failures produce no event (level, not transition)."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    tracker.record_fetch(server_id=1, duration=0.1, success=False)
    tracker.record_fetch(server_id=1, duration=0.1, success=False)
    tracker.record_fetch(server_id=1, duration=0.1, success=False)

    assert tracker.record_fetch(server_id=1, duration=0.1, success=False) is None
    assert tracker.record_fetch(server_id=1, duration=0.1, success=False) is None


@pytest.mark.unit
def test_success_after_unhealthy_fires_recovery_event_and_resets_count():
    """A success after unhealthy (consecutive failures) fires a recovery event."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    tracker.record_fetch(server_id=1, duration=0.1, success=False)
    tracker.record_fetch(server_id=1, duration=0.1, success=False)
    tracker.record_fetch(server_id=1, duration=0.1, success=False)

    event = tracker.record_fetch(server_id=1, duration=0.2, success=True)

    assert event == {
        "scope": "server",
        "server_id": 1,
        "healthy": True,
        "reason": "recovered",
        "consecutive_failures": 0,
        "last_duration": 0.2,
    }

    # Failure count has been reset: two more failures should not yet fire.
    assert tracker.record_fetch(server_id=1, duration=0.1, success=False) is None
    assert tracker.record_fetch(server_id=1, duration=0.1, success=False) is None


@pytest.mark.unit
def test_slow_fetch_fires_unhealthy_event():
    """A successful fetch exceeding SLOW_FETCH_THRESHOLD_SEC is a slow-fetch transition."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    event = tracker.record_fetch(server_id=2, duration=6.0, success=True)

    assert event == {
        "scope": "server",
        "server_id": 2,
        "healthy": False,
        "reason": "slow_fetch",
        "consecutive_failures": 0,
        "last_duration": 6.0,
    }


@pytest.mark.unit
def test_slow_fetch_recovery_when_duration_drops_below_threshold():
    """After a slow fetch, a subsequent fast fetch fires a recovery event."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    tracker.record_fetch(server_id=2, duration=6.0, success=True)
    event = tracker.record_fetch(server_id=2, duration=1.0, success=True)

    assert event == {
        "scope": "server",
        "server_id": 2,
        "healthy": True,
        "reason": "recovered",
        "consecutive_failures": 0,
        "last_duration": 1.0,
    }


@pytest.mark.unit
def test_successive_slow_fetches_only_first_fires():
    """Repeated slow fetches after the first should not re-fire the event."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    first = tracker.record_fetch(server_id=2, duration=6.0, success=True)
    second = tracker.record_fetch(server_id=2, duration=7.0, success=True)

    assert first is not None
    assert first["reason"] == "slow_fetch"
    assert second is None


@pytest.mark.unit
def test_cycle_crossing_above_budget_fires_event():
    """A cycle duration crossing above CYCLE_BUDGET_RATIO * interval fires an event."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    event = tracker.record_cycle(duration=9.0, interval=10.0)

    assert event == {
        "scope": "cycle",
        "duration": 9.0,
        "interval": 10.0,
        "budget_exceeded": True,
    }


@pytest.mark.unit
def test_cycle_staying_above_budget_no_event():
    """Staying above budget on the next call fires no event (edge-triggered)."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    tracker.record_cycle(duration=9.0, interval=10.0)
    event = tracker.record_cycle(duration=9.5, interval=10.0)

    assert event is None


@pytest.mark.unit
def test_cycle_dropping_back_below_budget_fires_event():
    """Dropping back below budget fires a recovery-style cycle event."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    tracker.record_cycle(duration=9.0, interval=10.0)
    event = tracker.record_cycle(duration=2.0, interval=10.0)

    assert event == {
        "scope": "cycle",
        "duration": 2.0,
        "interval": 10.0,
        "budget_exceeded": False,
    }


@pytest.mark.unit
def test_cycle_staying_below_budget_no_event_including_first_call():
    """Staying below budget - including the very first call - fires no event."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    assert tracker.record_cycle(duration=1.0, interval=10.0) is None
    assert tracker.record_cycle(duration=2.0, interval=10.0) is None


@pytest.mark.unit
def test_snapshot_shape_before_any_cycle():
    """Before any cycle is recorded, snapshot()["cycle"] is None."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    tracker.record_fetch(server_id=1, duration=0.5, success=True)

    snapshot = tracker.snapshot()
    assert snapshot == {
        "servers": {
            1: {"healthy": True, "consecutive_failures": 0, "last_duration": 0.5},
        },
        "cycle": None,
    }


@pytest.mark.unit
def test_snapshot_reflects_server_and_cycle_state():
    """snapshot() reflects both per-server health and the latest cycle state."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    tracker.record_fetch(server_id=1, duration=0.1, success=False)
    tracker.record_fetch(server_id=1, duration=0.1, success=False)
    tracker.record_fetch(server_id=1, duration=0.1, success=False)
    tracker.record_cycle(duration=9.0, interval=10.0)

    snapshot = tracker.snapshot()
    assert snapshot == {
        "servers": {
            1: {"healthy": False, "consecutive_failures": 3, "last_duration": 0.1},
        },
        "cycle": {"duration": 9.0, "interval": 10.0, "budget_exceeded": True},
    }


@pytest.mark.unit
def test_prune_removes_servers_not_in_active_set():
    """prune() removes servers absent from the given active server id collection."""
    from services.sync_engine import PollHealthTracker
    tracker = PollHealthTracker()

    tracker.record_fetch(server_id=1, duration=0.1, success=True)
    tracker.record_fetch(server_id=2, duration=0.1, success=True)

    tracker.prune(active_server_ids=[1])

    snapshot = tracker.snapshot()
    assert 1 in snapshot["servers"]
    assert 2 not in snapshot["servers"]


# =============================================================================
# TestPollHealthIntegration - check_quadlets() publishing poll_health events
# =============================================================================


@pytest.mark.asyncio
@patch("services.sync_engine.publisher")
@patch("services.sync_engine.pool")
@patch("services.sync_engine.get_db_connection")
@pytest.mark.unit
async def test_check_quadlets_publishes_poll_health_after_three_failures(
    mock_get_db_func, mock_pool, mock_publisher
):
    """After three consecutive SSH failures for a server, check_quadlets() should
    publish a poll_health event marking that server unhealthy."""
    import services.sync_engine as sync_engine_module

    # Reset tracker state so failure counts start clean for this test.
    sync_engine_module.health_tracker = sync_engine_module.PollHealthTracker()

    quadlet_row = {
        "id": 20,
        "server_id": 42,
        "file_path": "/etc/containers/systemd/flaky.container",
        "scope": "global",
        "last_known_mtime": 1000,
    }

    mock_pool.execute_command = AsyncMock(side_effect=ConnectionError("SSH timeout"))
    mock_publisher.publish = AsyncMock()

    for _ in range(3):
        select_cm, _ = _make_db_cm([quadlet_row])
        mock_get_db_func.side_effect = [select_cm]
        await check_quadlets()

    poll_health_calls = [
        call for call in mock_publisher.publish.call_args_list
        if call.args[0] == "poll_health"
    ]
    assert len(poll_health_calls) >= 1
    payload = poll_health_calls[-1].args[1]
    assert payload["healthy"] is False


# =============================================================================
# TestPollHealthEndpoint - GET /api/poll-health route
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.unit
async def test_api_poll_health_returns_tracker_snapshot():
    """api_poll_health() returns JSON equal to health_tracker.snapshot()."""
    from api.routes import api_poll_health
    from services.sync_engine import health_tracker

    response = await api_poll_health(role="admin")

    assert response.body is not None
    import json as _json
    # Compare through a JSON round-trip on both sides: snapshot() legitimately
    # uses int server-id keys (asserted directly elsewhere), but JSON always
    # serializes dict keys as strings, so a raw comparison against the live
    # snapshot() would spuriously fail whenever any server is tracked.
    assert _json.loads(response.body) == _json.loads(_json.dumps(health_tracker.snapshot()))
