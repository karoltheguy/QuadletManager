"""Tests for per-server scope_filter feature (issue #28).

Covers:
- stats_engine respects scope_filter ('user', 'global', 'both')
- tree_scanner fetch_all_quadlets respects scope_filter
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# Stats engine scope filtering
# =============================================================================

def _make_db_mock_with_scope(server_rows):
    """Build a mock for get_db_connection() returning rows with scope_filter."""
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=server_rows)

    mock_cursor_cm = AsyncMock()
    mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor_cm.__aexit__ = AsyncMock(return_value=False)

    mock_db = AsyncMock()
    mock_db.execute = MagicMock(return_value=mock_cursor_cm)

    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=mock_db_cm)


@pytest.mark.asyncio
@patch("services.stats_engine._record_health_history", new_callable=AsyncMock)
@patch("services.stats_engine.publisher")
@patch("services.stats_engine._fetch_scope_stats")
@patch("services.stats_engine.get_db_connection")
@pytest.mark.unit
async def test_scope_filter_both_fetches_both_scopes(mock_get_db, mock_fetch, mock_publisher, mock_record):
    """scope_filter='both' must fetch user AND global containers."""
    from services.stats_engine import fetch_server_stats

    # Row: (id, name, scope_filter)
    mock_get_db.side_effect = _make_db_mock_with_scope([(1, "mybox", "both")])
    user_c = [{"name": "user-app", "cpu": "1%", "mem": "2%",
               "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "1"}]
    global_c = [{"name": "sys-svc", "cpu": "3%", "mem": "4%",
                 "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "2"}]
    mock_fetch.side_effect = [user_c, global_c]
    mock_publisher.publish = AsyncMock()

    await fetch_server_stats()

    assert mock_fetch.call_count == 2
    calls = {(c[1]["rootful"]) for c in mock_fetch.call_args_list}
    assert calls == {False, True}

    payload = mock_publisher.publish.call_args[0][1]
    assert len(payload["containers"]) == 2


@pytest.mark.asyncio
@patch("services.stats_engine._record_health_history", new_callable=AsyncMock)
@patch("services.stats_engine.publisher")
@patch("services.stats_engine._fetch_scope_stats")
@patch("services.stats_engine.get_db_connection")
@pytest.mark.unit
async def test_scope_filter_user_only_skips_global(mock_get_db, mock_fetch, mock_publisher, mock_record):
    """scope_filter='user' must only fetch rootless containers, never rootful."""
    from services.stats_engine import fetch_server_stats

    mock_get_db.side_effect = _make_db_mock_with_scope([(1, "mybox", "user")])
    user_c = [{"name": "user-app", "cpu": "1%", "mem": "2%",
               "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "1"}]
    mock_fetch.return_value = user_c
    mock_publisher.publish = AsyncMock()

    await fetch_server_stats()

    assert mock_fetch.call_count == 1
    assert mock_fetch.call_args[1]["rootful"] is False

    payload = mock_publisher.publish.call_args[0][1]
    assert len(payload["containers"]) == 1
    assert payload["containers"][0]["name"] == "user-app"


@pytest.mark.asyncio
@patch("services.stats_engine._record_health_history", new_callable=AsyncMock)
@patch("services.stats_engine.publisher")
@patch("services.stats_engine._fetch_scope_stats")
@patch("services.stats_engine.get_db_connection")
@pytest.mark.unit
async def test_scope_filter_global_only_skips_user(mock_get_db, mock_fetch, mock_publisher, mock_record):
    """scope_filter='global' must only fetch rootful containers, never rootless."""
    from services.stats_engine import fetch_server_stats

    mock_get_db.side_effect = _make_db_mock_with_scope([(1, "mybox", "global")])
    global_c = [{"name": "sys-svc", "cpu": "5%", "mem": "8%",
                 "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "3"}]
    mock_fetch.return_value = global_c
    mock_publisher.publish = AsyncMock()

    await fetch_server_stats()

    assert mock_fetch.call_count == 1
    assert mock_fetch.call_args[1]["rootful"] is True

    payload = mock_publisher.publish.call_args[0][1]
    assert len(payload["containers"]) == 1
    assert payload["containers"][0]["name"] == "sys-svc"


# =============================================================================
# Tree scanner scope filtering
# =============================================================================

@pytest.mark.asyncio
@patch("services.tree_scanner.scan_directory")
@pytest.mark.unit
async def test_fetch_all_quadlets_both_scans_both(mock_scan):
    """scope_filter='both' scans global and user directories."""
    from services.tree_scanner import fetch_all_quadlets

    mock_scan.side_effect = [
        [{"path": "/etc/containers/systemd/nginx.container", "name": "nginx.container", "scope": "global"}],
        [{"path": "~/.config/containers/systemd/app.container", "name": "app.container", "scope": "user"}],
    ]

    result = await fetch_all_quadlets(server_id=1, scope_filter="both")

    assert mock_scan.call_count == 2
    assert len(result["global"]) == 1
    assert len(result["user"]) == 1


@pytest.mark.asyncio
@patch("services.tree_scanner.scan_directory")
@pytest.mark.unit
async def test_fetch_all_quadlets_user_only(mock_scan):
    """scope_filter='user' only scans user directory, global is empty."""
    from services.tree_scanner import fetch_all_quadlets

    mock_scan.return_value = [
        {"path": "~/.config/containers/systemd/app.container", "name": "app.container", "scope": "user"}
    ]

    result = await fetch_all_quadlets(server_id=1, scope_filter="user")

    assert mock_scan.call_count == 1
    called_path = mock_scan.call_args[0][1]
    assert "config" in called_path  # USER_DIR
    assert result["global"] == []
    assert len(result["user"]) == 1


@pytest.mark.asyncio
@patch("services.tree_scanner.scan_directory")
@pytest.mark.unit
async def test_fetch_all_quadlets_global_only(mock_scan):
    """scope_filter='global' only scans global directory, user is empty."""
    from services.tree_scanner import fetch_all_quadlets

    mock_scan.return_value = [
        {"path": "/etc/containers/systemd/nginx.container", "name": "nginx.container", "scope": "global"}
    ]

    result = await fetch_all_quadlets(server_id=1, scope_filter="global")

    assert mock_scan.call_count == 1
    called_path = mock_scan.call_args[0][1]
    assert "etc" in called_path  # GLOBAL_DIR
    assert result["user"] == []
    assert len(result["global"]) == 1


@pytest.mark.asyncio
@patch("services.tree_scanner.scan_directory")
@pytest.mark.unit
async def test_fetch_all_quadlets_defaults_to_both(mock_scan):
    """fetch_all_quadlets without scope_filter defaults to 'both'."""
    from services.tree_scanner import fetch_all_quadlets

    mock_scan.side_effect = [[], []]

    result = await fetch_all_quadlets(server_id=1)

    assert mock_scan.call_count == 2
