"""
Tests for the /api/overview endpoint and the Overview tab UI (issue #79).

Unit tests mock the DB directly and call the route function.
Playwright tests require the backend on localhost:8000.
"""
import sys
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# =============================================================================
# Helpers
# =============================================================================

def _make_db_mock(servers_rows, history_rows):
    """
    Build an aiosqlite mock that returns different rows depending on which
    execute() call is made.  First call → servers_rows, subsequent calls →
    history_rows (one per server).
    """
    call_count = 0

    def _make_cursor(rows):
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=cursor)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    mock_db = AsyncMock()

    def _execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_cursor(servers_rows)
        return _make_cursor(history_rows)

    mock_db.execute = MagicMock(side_effect=_execute_side_effect)

    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=mock_db_cm)


# =============================================================================
# Unit tests: /api/overview API endpoint
# =============================================================================

@pytest.mark.asyncio
@patch("api.routes.get_db_connection")
async def test_overview_returns_html_response(mock_get_db):
    """Endpoint must return an HTMLResponse."""
    from fastapi.responses import HTMLResponse
    from api.routes import api_overview

    mock_get_db.return_value = _make_db_mock(
        servers_rows=[],
        history_rows=[],
    ).return_value

    mock_request = MagicMock()
    response = await api_overview(mock_request)
    assert response.status_code == 200
    assert "text/html" in response.media_type


@pytest.mark.asyncio
@patch("api.routes.get_db_connection")
async def test_overview_empty_state_when_no_servers(mock_get_db):
    """When no servers are configured, the response contains the empty state marker."""
    from api.routes import api_overview

    mock_get_db.return_value = _make_db_mock(
        servers_rows=[],
        history_rows=[],
    ).return_value

    mock_request = MagicMock()
    response = await api_overview(mock_request)
    body = response.body.decode()
    assert "overview-empty" in body


@pytest.mark.asyncio
@patch("api.routes.get_db_connection")
async def test_overview_shows_health_badge_for_healthy_container(mock_get_db):
    """Running containers with a non-empty health_status must show a health badge."""
    from api.routes import api_overview

    servers_rows = [(1, "prod-server")]
    # 3-tuple: name, is_running, health_status
    history_rows = [("nginx", 1, "healthy")]

    call_count = 0

    def _make_cursor(rows):
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=cursor)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    mock_db = AsyncMock()

    def _execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_cursor(servers_rows if call_count == 1 else history_rows)

    mock_db.execute = MagicMock(side_effect=_execute_side_effect)
    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)
    mock_get_db.return_value = mock_db_cm

    mock_request = MagicMock()
    response = await api_overview(mock_request)
    body = response.body.decode()

    assert "overview-health-badge" in body
    assert "healthy" in body


@pytest.mark.asyncio
@patch("api.routes.get_db_connection")
async def test_overview_no_health_badge_when_status_empty(mock_get_db):
    """Running containers with no healthcheck (empty status) must not show a badge."""
    from api.routes import api_overview

    servers_rows = [(1, "prod-server")]
    history_rows = [("redis", 1, "")]

    call_count = 0

    def _make_cursor(rows):
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=cursor)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    mock_db = AsyncMock()

    def _execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_cursor(servers_rows if call_count == 1 else history_rows)

    mock_db.execute = MagicMock(side_effect=_execute_side_effect)
    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)
    mock_get_db.return_value = mock_db_cm

    mock_request = MagicMock()
    response = await api_overview(mock_request)
    body = response.body.decode()

    assert "overview-health-badge" not in body


@pytest.mark.asyncio
@patch("api.routes.get_db_connection")
async def test_overview_aggregates_running_and_stopped_counts(mock_get_db):
    """With one server and mixed container statuses, counts must appear in the HTML."""
    from api.routes import api_overview

    servers_rows = [(1, "prod-server")]
    # Latest snapshot per container: name + is_running + health_status (3 cols)
    history_rows = [
        ("nginx", 1, "healthy"),
        ("redis", 0, None),
    ]

    call_count = 0

    def _make_cursor(rows):
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=cursor)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    mock_db = AsyncMock()

    def _execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_cursor(servers_rows if call_count == 1 else history_rows)

    mock_db.execute = MagicMock(side_effect=_execute_side_effect)
    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)
    mock_get_db.return_value = mock_db_cm

    mock_request = MagicMock()
    response = await api_overview(mock_request)
    body = response.body.decode()

    # Server name must appear
    assert "prod-server" in body
    # Container names must appear
    assert "nginx" in body
    assert "redis" in body


@pytest.mark.asyncio
@patch("api.routes.get_db_connection")
async def test_overview_total_counts_in_stat_tiles(mock_get_db):
    """Summary stat totals must be rendered in the response."""
    from api.routes import api_overview

    servers_rows = [(1, "prod-server"), (2, "staging-server")]
    history_rows_s1 = [("nginx", 1, "healthy"), ("redis", 0, None)]

    call_count = 0

    def _make_cursor_for(rows):
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=cursor)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    mock_db = AsyncMock()

    def _execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_cursor_for(servers_rows)
        return _make_cursor_for(history_rows_s1)

    mock_db.execute = MagicMock(side_effect=_execute_side_effect)
    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)
    mock_get_db.return_value = mock_db_cm

    mock_request = MagicMock()
    response = await api_overview(mock_request)
    body = response.body.decode()

    # Both server names should appear
    assert "prod-server" in body
    assert "staging-server" in body


@pytest.mark.asyncio
@patch("api.routes.get_db_connection")
async def test_overview_deduplicates_duplicate_db_rows(mock_get_db):
    """When DB returns duplicate rows for the same container name (e.g. from
    scope-collision writes), each container must appear exactly once in the HTML."""
    from api.routes import api_overview

    servers_rows = [(1, "prod-server")]
    # Simulate two identical rows for 'nginx' — same name, same status
    history_rows = [
        ("nginx", 1, "healthy"),
        ("nginx", 1, "healthy"),
    ]

    call_count = 0

    def _make_cursor(rows):
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=cursor)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    mock_db = AsyncMock()

    def _execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_cursor(servers_rows if call_count == 1 else history_rows)

    mock_db.execute = MagicMock(side_effect=_execute_side_effect)
    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)
    mock_get_db.return_value = mock_db_cm

    mock_request = MagicMock()
    response = await api_overview(mock_request)
    body = response.body.decode()

    # nginx should appear exactly once as a container entry, not twice
    # The overview template renders each container in a list item with the name
    container_count = body.count("nginx")
    assert container_count == 1, (
        f"Expected 'nginx' to appear exactly once, but found {container_count} occurrences. "
        "Duplicate DB rows are leaking through to the rendered output."
    )

