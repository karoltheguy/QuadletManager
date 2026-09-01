"""
E2E tests for the profile menu (Issue #414).

Requires the backend running at QM_APP_URL and Playwright installed.
Run with: pytest tests/e2e/test_profile_menu.py
"""
import pytest  # type: ignore

try:
    from playwright.sync_api import Page, expect  # type: ignore
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Page = typing.Any  # type: ignore
    def expect(x: typing.Any) -> typing.Any: pass

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="Playwright is not installed in this environment"
)

from tests.app_url import BASE_URL


def _goto(page: Page):
    """Navigate to the dashboard, skip test if backend is not running."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip(f"Backend is not running on {BASE_URL}, skipping E2E tests.")


@pytest.mark.e2e
def test_clicking_profile_button_opens_and_keeps_menu_visible(page: Page):
    """Clicking #profile-btn must open #profile-menu and it must stay open.

    Regression: the document-level click listener that closes the menu must not
    also swallow the very click that opened it.
    """
    _goto(page)
    menu = page.locator("#profile-menu")
    expect(menu).not_to_be_visible()

    page.click("#profile-btn")

    expect(menu).to_be_visible()


@pytest.mark.e2e
def test_clicking_elsewhere_closes_open_profile_menu(page: Page):
    """With the menu open, clicking elsewhere on the page must close it."""
    _goto(page)
    menu = page.locator("#profile-menu")

    page.click("#profile-btn")
    expect(menu).to_be_visible()

    page.click(".nav-brand")

    expect(menu).not_to_be_visible()
