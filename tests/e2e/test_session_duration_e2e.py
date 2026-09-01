"""
E2E tests for the configurable session duration setting (Issue #124).
"""
import pytest

try:
    from playwright.sync_api import Page, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Page = typing.Any

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="Playwright is not installed in this environment"
)

from tests.e2e.app_page import goto_app


def _goto_admin_section(page: Page):
    goto_app(page)
    page.click("button.nav-item:has-text('Settings')")
    expect(page.locator("#settings-pane")).to_be_visible()
    page.click(".settings-sidenav-item[data-section='admin']")
    expect(page.locator(".settings-group[data-group='admin']")).to_be_visible()


@pytest.mark.e2e
def test_admin_tab_appears_in_settings_sidenav(page: Page):
    """Settings sidenav must show an Admin item that reveals the session duration control."""
    _goto_admin_section(page)
    duration_select = page.locator("select[name='session_duration_seconds']")
    expect(duration_select).to_be_visible(timeout=5000)


@pytest.mark.e2e
def test_session_duration_change_persists_after_reload(page: Page):
    """Selecting a new duration must persist server-side and survive a page reload."""
    _goto_admin_section(page)
    duration_select = page.locator("select[name='session_duration_seconds']")
    expect(duration_select).to_be_visible(timeout=5000)

    original_value = duration_select.input_value()
    new_value = "2592000" if original_value != "2592000" else "604800"  # 1 month / 1 week

    with page.expect_response("**/api/settings/session-duration"):
        duration_select.select_option(new_value)

    try:
        page.reload()
        _goto_admin_section(page)
        reloaded_select = page.locator("select[name='session_duration_seconds']")
        expect(reloaded_select).to_have_value(new_value, timeout=5000)
    finally:
        with page.expect_response("**/api/settings/session-duration"):
            page.locator("select[name='session_duration_seconds']").select_option(original_value)
