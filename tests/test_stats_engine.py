"""Tests for stats_engine module.

Migrated from unittest.IsolatedAsyncioTestCase to pytest-asyncio native style
to resolve event loop conflict (Issue #19).
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.stats_engine import (
    normalize_container_stats,
    fetch_server_stats,
    _fetch_scope_stats,
    _parse_pct,
    _record_health_history,
    ROOTLESS_ENV_PREFIX,
)


# =============================================================================
# TestNormalizeContainerStats - pure sync function tests
# =============================================================================


def test_podman_v4_format():
    """Podman 4.x uses keys like 'CPUPerc', 'MemPerc', etc."""
    raw = {
        "Name": "nginx",
        "CPUPerc": "12.34%",
        "MemPerc": "5.67%",
        "MemUsage": "128MiB / 2GiB",
        "NetIO": "1.2kB / 3.4kB",
        "BlockIO": "500B / 1kB",
        "PIDs": "4",
    }
    result = normalize_container_stats(raw)

    assert result["name"] == "nginx"
    assert result["cpu"] == "12.34%"
    assert result["mem"] == "5.67%"
    assert result["mem_usage"] == "128MiB / 2GiB"
    assert result["net_io"] == "1.2kB / 3.4kB"
    assert result["block_io"] == "500B / 1kB"
    assert result["pids"] == "4"


def test_podman_v3_format():
    """Podman 3.x uses lowercase keys like 'cpu_percent', 'mem_percent'."""
    raw = {
        "name": "redis",
        "cpu_percent": "0.50%",
        "mem_percent": "2.10%",
        "mem_usage": "64MiB / 1GiB",
        "net_io": "800B / 200B",
        "block_io": "0B / 0B",
        "pids": "1",
    }
    result = normalize_container_stats(raw)

    assert result["name"] == "redis"
    assert result["cpu"] == "0.50%"
    assert result["mem"] == "2.10%"
    assert result["net_io"] == "800B / 200B"
    assert result["pids"] == "1"


def test_missing_fields_fallback_to_defaults():
    """If a field is completely absent, we get safe defaults (no KeyError)."""
    raw = {}
    result = normalize_container_stats(raw)

    assert result["name"] == "unknown"
    assert result["cpu"] == "0%"
    assert result["mem"] == "0%"
    assert result["mem_usage"] == "—"
    assert result["net_io"] == "—"
    assert result["block_io"] == "—"
    assert result["pids"] == "0"


def test_mixed_keys_prefers_lowercase():
    """When both v3 and v4 keys exist, lowercase (v3) wins because
    of the `or` chain order in normalize_container_stats."""
    raw = {
        "name": "mixed",
        "Name": "MIXED_UPPER",
        "cpu_percent": "1.00%",
        "CPUPerc": "99.00%",
    }
    result = normalize_container_stats(raw)

    assert result["name"] == "mixed"
    assert result["cpu"] == "1.00%"


def test_empty_string_values_treated_as_missing():
    """Empty strings are falsy, so the fallback should kick in."""
    raw = {
        "name": "",
        "cpu_percent": "",
        "mem_percent": "",
    }
    result = normalize_container_stats(raw)

    # Empty name falls through to "Name" key (also missing) → "unknown"
    assert result["name"] == "unknown"
    assert result["cpu"] == "0%"
    assert result["mem"] == "0%"


def test_all_keys_present_in_output():
    """Verify the output always contains exactly the expected keys."""
    raw = {"name": "test"}
    result = normalize_container_stats(raw)
    expected_keys = {"name", "cpu", "mem", "mem_usage", "net_io", "block_io", "pids"}

    assert set(result.keys()) == expected_keys


# =============================================================================
# TestFetchScopeStats - async tests for _fetch_scope_stats()
# =============================================================================


@pytest.mark.asyncio
@patch("services.stats_engine.pool")
async def test_rootless_commands_include_env_prefix(mock_pool):
    """Rootless (user) scope must prefix commands with XDG_RUNTIME_DIR."""
    ps_json = json.dumps([{"Names": "app", "HealthStatus": ""}])
    stats_json = json.dumps([{"name": "app", "cpu_percent": "1%", "mem_percent": "2%"}])
    mock_pool.execute_command = AsyncMock(side_effect=[ps_json, stats_json])

    result = await _fetch_scope_stats(server_id=1, rootful=False)

    assert len(result) == 1
    assert result[0]["name"] == "app"

    # Verify the ps command includes the env prefix
    ps_call = mock_pool.execute_command.call_args_list[0]
    assert ROOTLESS_ENV_PREFIX in ps_call[0][1]
    assert "sudo" not in ps_call[0][1]

    # Verify the stats command also includes the env prefix
    stats_call = mock_pool.execute_command.call_args_list[1]
    assert ROOTLESS_ENV_PREFIX in stats_call[0][1]
    assert "sudo" not in stats_call[0][1]


@pytest.mark.asyncio
@patch("services.stats_engine.pool")
async def test_rootful_commands_use_sudo(mock_pool):
    """Global (rootful) scope must use sudo, not the env prefix."""
    ps_json = json.dumps([{"Names": "system-app", "HealthStatus": ""}])
    stats_json = json.dumps([{"Name": "system-app", "CPUPerc": "5%", "MemPerc": "10%"}])
    mock_pool.execute_command = AsyncMock(side_effect=[ps_json, stats_json])

    result = await _fetch_scope_stats(server_id=1, rootful=True)

    assert len(result) == 1
    assert result[0]["name"] == "system-app"

    # Verify sudo is used
    ps_call = mock_pool.execute_command.call_args_list[0]
    assert "sudo" in ps_call[0][1]

    stats_call = mock_pool.execute_command.call_args_list[1]
    assert "sudo" in stats_call[0][1]


@pytest.mark.asyncio
@patch("services.stats_engine.pool")
async def test_no_running_containers_returns_empty(mock_pool):
    """If podman ps returns an empty JSON array, we get an empty list (no crash)."""
    mock_pool.execute_command = AsyncMock(return_value="[]")

    result = await _fetch_scope_stats(server_id=1, rootful=False)

    assert result == []
    # Only one call (ps), no stats call needed
    assert mock_pool.execute_command.call_count == 1


@pytest.mark.asyncio
@patch("services.stats_engine.pool")
async def test_ssh_error_returns_empty_list(mock_pool):
    """SSH errors are caught and logged; an empty list is returned."""
    mock_pool.execute_command = AsyncMock(side_effect=Exception("Connection refused"))

    result = await _fetch_scope_stats(server_id=1, rootful=False)

    assert result == []


@pytest.mark.asyncio
@patch("services.stats_engine.pool")
async def test_invalid_json_returns_empty_list(mock_pool):
    """If podman stats returns garbage, we return an empty list."""
    ps_json = json.dumps([{"Names": "app", "HealthStatus": ""}])
    mock_pool.execute_command = AsyncMock(side_effect=[ps_json, "not json"])

    result = await _fetch_scope_stats(server_id=1, rootful=True)

    assert result == []


@pytest.mark.asyncio
@patch("services.stats_engine.pool")
async def test_fetch_scope_stats_uses_json_ps_format(mock_pool):
    """podman ps must use --format json so health status can be parsed."""
    stats_json = json.dumps([{"name": "app", "cpu_percent": "1%", "mem_percent": "2%"}])
    ps_json = json.dumps([{"Names": "app", "HealthStatus": "healthy"}])
    mock_pool.execute_command = AsyncMock(side_effect=[ps_json, stats_json])

    await _fetch_scope_stats(server_id=1, rootful=False)

    ps_call = mock_pool.execute_command.call_args_list[0]
    assert "--format json" in ps_call[0][1]


@pytest.mark.asyncio
@patch("services.stats_engine.pool")
async def test_health_status_included_in_result(mock_pool):
    """Containers with a healthcheck must have their health status in the result dict."""
    ps_json = json.dumps([{"Names": "nginx", "HealthStatus": "healthy"}])
    stats_json = json.dumps([{"name": "nginx", "cpu_percent": "5%", "mem_percent": "10%"}])
    mock_pool.execute_command = AsyncMock(side_effect=[ps_json, stats_json])

    result = await _fetch_scope_stats(server_id=1, rootful=False)

    assert len(result) == 1
    assert result[0]["health"] == "healthy"


@pytest.mark.asyncio
@patch("services.stats_engine.pool")
async def test_health_status_defaults_to_empty_when_absent(mock_pool):
    """Containers without a healthcheck definition have health == '' (not an error)."""
    ps_json = json.dumps([{"Names": "redis", "HealthStatus": ""}])
    stats_json = json.dumps([{"name": "redis", "cpu_percent": "1%", "mem_percent": "2%"}])
    mock_pool.execute_command = AsyncMock(side_effect=[ps_json, stats_json])

    result = await _fetch_scope_stats(server_id=1, rootful=False)

    assert result[0]["health"] == ""


@pytest.mark.asyncio
@patch("services.stats_engine.pool")
async def test_health_status_names_as_list(mock_pool):
    """Names returned as a JSON array (older Podman) must still be parsed correctly."""
    ps_json = json.dumps([{"Names": ["app"], "HealthStatus": "unhealthy"}])
    stats_json = json.dumps([{"name": "app", "cpu_percent": "1%", "mem_percent": "2%"}])
    mock_pool.execute_command = AsyncMock(side_effect=[ps_json, stats_json])

    result = await _fetch_scope_stats(server_id=1, rootful=False)

    assert result[0]["name"] == "app"
    assert result[0]["health"] == "unhealthy"


@pytest.mark.asyncio
@patch("services.stats_engine.get_db_connection")
async def test_record_health_history_includes_health_status(mock_get_db):
    """Health status must be stored as the 7th element in each INSERT record."""
    mock_get_db_fn, mock_db = _make_health_db_mock()
    mock_get_db.return_value = mock_get_db_fn.return_value

    import services.stats_engine as se
    se._prev_running_by_sid.pop(55, None)

    containers = [{"name": "nginx", "cpu": "5%", "mem": "10%", "health": "healthy"}]
    await _record_health_history(55, containers)

    records = mock_db.executemany.call_args[0][1]
    assert len(records) == 1
    # index 7 is health_status (index 6 is resolution_sec, added for rollup support)
    assert records[0][7] == "healthy"


# =============================================================================
# TestFetchServerStats - async tests for fetch_server_stats()
# =============================================================================


def _make_db_mock(server_rows):
    """Build a mock that satisfies:
    async with get_db_connection() as db:
        async with db.execute(...) as cursor:
            rows = await cursor.fetchall()
    """
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=server_rows)

    # db.execute(...) must return an async context manager yielding the cursor
    mock_cursor_cm = AsyncMock()
    mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor_cm.__aexit__ = AsyncMock(return_value=False)

    mock_db = AsyncMock()
    mock_db.execute = MagicMock(return_value=mock_cursor_cm)

    # get_db_connection() is now a regular function returning an async CM
    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)

    mock_get_db = MagicMock(return_value=mock_db_cm)
    return mock_get_db


@pytest.mark.asyncio
@patch("services.stats_engine._record_health_history", new_callable=AsyncMock)
@patch("services.stats_engine.publisher")
@patch("services.stats_engine._fetch_scope_stats")
@patch("services.stats_engine.get_db_connection")
async def test_merges_user_and_global_containers(mock_get_db, mock_fetch, mock_publisher, mock_record):
    """fetch_server_stats should merge rootless + rootful containers."""
    mock_get_db.side_effect = _make_db_mock([(1, "testbox")])

    user_containers = [{"name": "user-app", "cpu": "1%", "mem": "2%",
                        "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "1"}]
    global_containers = [{"name": "system-svc", "cpu": "3%", "mem": "4%",
                          "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "2"}]

    # _fetch_scope_stats is called twice: once rootful=False, once rootful=True
    mock_fetch.side_effect = [user_containers, global_containers]
    mock_publisher.publish = AsyncMock()

    await fetch_server_stats()

    mock_publisher.publish.assert_called_once()
    call_args = mock_publisher.publish.call_args
    assert call_args[0][0] == "stats_update"

    payload = call_args[0][1]
    assert payload["server_id"] == 1
    assert payload["server_name"] == "testbox"
    assert len(payload["containers"]) == 2
    names = [c["name"] for c in payload["containers"]]
    assert "user-app" in names
    assert "system-svc" in names


@pytest.mark.asyncio
@patch("services.stats_engine._record_health_history", new_callable=AsyncMock)
@patch("services.stats_engine.publisher")
@patch("services.stats_engine._fetch_scope_stats")
@patch("services.stats_engine.get_db_connection")
async def test_empty_both_scopes_publishes_empty(mock_get_db, mock_fetch, mock_publisher, mock_record):
    """When no containers run in either scope, publish empty update."""
    mock_get_db.side_effect = _make_db_mock([(2, "emptybox")])

    mock_fetch.side_effect = [[], []]
    mock_publisher.publish = AsyncMock()

    await fetch_server_stats()

    mock_publisher.publish.assert_called_once_with("stats_update", {
        "server_id": 2,
        "server_name": "emptybox",
        "containers": [],
    })


@pytest.mark.asyncio
@patch("services.stats_engine._record_health_history", new_callable=AsyncMock)
@patch("services.stats_engine.publisher")
@patch("services.stats_engine._fetch_scope_stats")
@patch("services.stats_engine.get_db_connection")
async def test_gather_exception_publishes_error(mock_get_db, mock_fetch, mock_publisher, mock_record):
    """If the gather itself raises, we publish a stats_error event."""
    mock_get_db.side_effect = _make_db_mock([(3, "badbox")])

    mock_fetch.side_effect = Exception("something broke")
    mock_publisher.publish = AsyncMock()

    await fetch_server_stats()

    mock_publisher.publish.assert_called_once_with("stats_error", {
        "server_id": 3,
        "server_name": "badbox",
        "error": "something broke",
    })


@pytest.mark.asyncio
@patch("services.stats_engine._record_health_history", new_callable=AsyncMock)
@patch("services.stats_engine.publisher")
@patch("services.stats_engine._fetch_scope_stats")
@patch("services.stats_engine.get_db_connection")
async def test_multiple_servers_each_publish(mock_get_db, mock_fetch, mock_publisher, mock_record):
    """When multiple servers exist, stats are fetched and published for each."""
    mock_get_db.side_effect = _make_db_mock([(1, "server-a"), (2, "server-b")])

    # Each server gets two _fetch_scope_stats calls (user + global)
    containers_a = [{"name": "app-a", "cpu": "1%", "mem": "2%",
                     "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "1"}]
    containers_b = [{"name": "app-b", "cpu": "3%", "mem": "4%",
                     "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "1"}]
    mock_fetch.side_effect = [containers_a, [], [], containers_b]
    mock_publisher.publish = AsyncMock()

    await fetch_server_stats()

    assert mock_publisher.publish.call_count == 2

    first_call = mock_publisher.publish.call_args_list[0][0]
    assert first_call[1]["server_name"] == "server-a"
    assert first_call[1]["containers"][0]["name"] == "app-a"

    second_call = mock_publisher.publish.call_args_list[1][0]
    assert second_call[1]["server_name"] == "server-b"
    assert second_call[1]["containers"][0]["name"] == "app-b"


# =============================================================================
# TestParsePct - pure sync helper
# =============================================================================


def test_parse_pct_string_with_percent():
    assert _parse_pct("5.23%") == pytest.approx(5.23)


def test_parse_pct_string_without_percent():
    assert _parse_pct("12.5") == pytest.approx(12.5)


def test_parse_pct_float():
    assert _parse_pct(3.14) == pytest.approx(3.14)


def test_parse_pct_int():
    assert _parse_pct(7) == pytest.approx(7.0)


def test_parse_pct_empty_string():
    assert _parse_pct("") == 0.0


def test_parse_pct_invalid_string():
    assert _parse_pct("N/A") == 0.0


def test_parse_pct_zero_string():
    assert _parse_pct("0%") == 0.0


# =============================================================================
# TestRecordHealthHistory - async persistence tests
# =============================================================================


def _make_health_db_mock():
    """Build a mock that satisfies executemany / execute / commit calls."""
    mock_db = AsyncMock()
    mock_db.executemany = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)

    mock_get_db = MagicMock(return_value=mock_db_cm)
    return mock_get_db, mock_db


@pytest.mark.asyncio
@patch("services.stats_engine.get_db_connection")
async def test_record_health_history_inserts_running_containers(mock_get_db):
    """Running containers must produce is_running=1 records."""
    mock_get_db_fn, mock_db = _make_health_db_mock()
    mock_get_db.side_effect = mock_get_db_fn.side_effect
    mock_get_db.return_value = mock_get_db_fn.return_value

    containers = [
        {"name": "nginx", "cpu": "5%", "mem": "10%"},
        {"name": "redis", "cpu": "1.5%", "mem": "3%"},
    ]
    import services.stats_engine as se
    se._prev_running_by_sid.pop(42, None)  # ensure clean state

    await _record_health_history(42, containers)

    mock_db.executemany.assert_called_once()
    records = mock_db.executemany.call_args[0][1]
    assert len(records) == 2
    names = [r[1] for r in records]
    assert "nginx" in names
    assert "redis" in names
    # All records should be is_running=1
    for r in records:
        assert r[2] == 1


@pytest.mark.asyncio
@patch("services.stats_engine.get_db_connection")
async def test_record_health_history_writes_stopped_for_disappeared(mock_get_db):
    """Containers that were running before but are absent now get is_running=0."""
    mock_get_db_fn, mock_db = _make_health_db_mock()
    mock_get_db.side_effect = mock_get_db_fn.side_effect
    mock_get_db.return_value = mock_get_db_fn.return_value

    import services.stats_engine as se
    se._prev_running_by_sid[99] = {"nginx", "redis"}

    # Now only nginx is running — redis disappeared
    await _record_health_history(99, [{"name": "nginx", "cpu": "2%", "mem": "5%"}])

    records = mock_db.executemany.call_args[0][1]
    by_name = {r[1]: r[2] for r in records}
    assert by_name["nginx"] == 1
    assert by_name["redis"] == 0


@pytest.mark.asyncio
@patch("services.stats_engine.get_db_connection")
async def test_record_health_history_skips_db_when_no_change(mock_get_db):
    """If containers list is empty and no prev containers, no DB write occurs."""
    mock_get_db_fn, mock_db = _make_health_db_mock()
    mock_get_db.side_effect = mock_get_db_fn.side_effect
    mock_get_db.return_value = mock_get_db_fn.return_value

    import services.stats_engine as se
    se._prev_running_by_sid.pop(77, None)

    await _record_health_history(77, [])

    mock_db.executemany.assert_not_called()
