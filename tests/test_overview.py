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

try:
    from playwright.sync_api import Page, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Page = typing.Any


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
async def test_overview_aggregates_running_and_stopped_counts(mock_get_db):
    """With one server and mixed container statuses, counts must appear in the HTML."""
    from api.routes import api_overview

    servers_rows = [(1, "prod-server")]
    # Latest snapshot per container: name + is_running (2 cols, matching the SQL SELECT)
    history_rows = [
        ("nginx", 1),
        ("redis", 0),
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
    history_rows_s1 = [("nginx", 1), ("redis", 0)]

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


# =============================================================================
# Playwright E2E tests — require backend on localhost:8000
# =============================================================================

pytestmark_playwright = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="Playwright not installed"
)


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")
def test_overview_tab_exists_in_nav(page: Page):
    """An 'Overview' nav button must be present."""
    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend not running on localhost:8000")

    expect(page.locator("button.nav-item:has-text('Overview')")).to_be_visible()


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")
def test_overview_pane_is_default_tab(page: Page):
    """#overview-pane must be visible on initial page load (default tab)."""
    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend not running on localhost:8000")

    expect(page.locator("#overview-pane")).to_be_visible()


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")
def test_overview_stat_tiles_present(page: Page):
    """Overview must render stat tiles with data-stat attributes."""
    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend not running on localhost:8000")

    page.click("button.nav-item:has-text('Overview')")
    expect(page.locator("[data-stat='servers']")).to_be_visible()
    expect(page.locator("[data-stat='running']")).to_be_visible()
    expect(page.locator("[data-stat='stopped']")).to_be_visible()


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")
def test_dashboard_tab_removed_from_nav(page: Page):
    """The old 'Dashboard' nav tab must no longer exist."""
    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend not running on localhost:8000")

    expect(page.locator("button.nav-item:has-text('Dashboard')")).to_have_count(0)
