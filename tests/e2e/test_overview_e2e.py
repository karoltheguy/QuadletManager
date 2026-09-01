"""Playwright E2E tests for the Overview tab (issue #79).

Requires the backend running at QM_APP_URL.
Unit tests (no browser required) live in tests/test_overview.py.
"""
import pytest
from tests.app_url import BASE_URL

try:
    from playwright.sync_api import Page, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Page = typing.Any

    def expect(x: typing.Any) -> typing.Any:
        pass

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT, reason="Playwright not installed"
)


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")
@pytest.mark.e2e
def test_overview_tab_exists_in_nav(page: Page):
    """An 'Overview' nav button must be present."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip(f"Backend not running on {BASE_URL}")

    expect(page.locator("button.nav-item:has-text('Overview')")).to_be_visible()


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")
@pytest.mark.e2e
def test_overview_pane_is_default_tab(page: Page):
    """#overview-pane must be visible on initial page load (default tab)."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip(f"Backend not running on {BASE_URL}")

    expect(page.locator("#overview-pane")).to_be_visible()


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")
@pytest.mark.e2e
def test_overview_stat_tiles_present(page: Page):
    """Overview must render stat tiles with data-stat attributes."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip(f"Backend not running on {BASE_URL}")

    page.click("button.nav-item:has-text('Overview')")
    expect(page.locator("[data-stat='servers']")).to_be_visible()
    expect(page.locator("[data-stat='running']")).to_be_visible()
    expect(page.locator("[data-stat='stopped']")).to_be_visible()


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")
@pytest.mark.e2e
def test_dashboard_tab_removed_from_nav(page: Page):
    """The old 'Dashboard' nav tab must no longer exist."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip(f"Backend not running on {BASE_URL}")

    expect(page.locator("button.nav-item:has-text('Dashboard')")).to_have_count(0)
