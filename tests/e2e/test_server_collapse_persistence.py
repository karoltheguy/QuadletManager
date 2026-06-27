"""
E2E tests for server row collapse state persistence (Issue #119).
"""
import pytest

try:
    from playwright.sync_api import Page
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    Page = type('Page', (object,), {})
    def expect(x): pass

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="Playwright is not installed in this environment"
)

BASE_URL = "http://localhost:8000"


def _goto_containers(page: Page):
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")
    page.click("button.nav-item:has-text('Containers')")


@pytest.mark.e2e
def test_collapse_saves_to_localstorage(page: Page):
    """Collapsing a server row must write its state to localStorage."""
    _goto_containers(page)

    server_rows = page.locator("li[data-server-id]")
    server_rows.first.wait_for(state="attached", timeout=5000)

    if server_rows.count() == 0:
        pytest.skip("No server rows present — skipping collapse test.")

    first_row = server_rows.first
    server_id = first_row.get_attribute("data-server-id")

    # Initially should not be collapsed
    assert not first_row.evaluate("el => el.classList.contains('is-collapsed')"), \
        "Server row should start expanded"

    toggle_btn = first_row.locator(".server-row-toggle")
    toggle_btn.click()

    # Row should now be collapsed
    assert first_row.evaluate("el => el.classList.contains('is-collapsed')"), \
        "Server row should be collapsed after clicking toggle"

    # localStorage must have been set
    stored = page.evaluate(
        "id => localStorage.getItem('qm-server-collapsed-' + id)",
        server_id
    )
    assert stored == "1", f"Expected '1' in localStorage, got {stored!r}"


@pytest.mark.e2e
def test_expand_saves_to_localstorage(page: Page):
    """Expanding a collapsed row must update localStorage to '0'."""
    _goto_containers(page)

    server_rows = page.locator("li[data-server-id]")
    server_rows.first.wait_for(state="attached", timeout=5000)

    if server_rows.count() == 0:
        pytest.skip("No server rows present — skipping collapse test.")

    first_row = server_rows.first
    server_id = first_row.get_attribute("data-server-id")
    toggle_btn = first_row.locator(".server-row-toggle")

    # Collapse then expand
    toggle_btn.click()
    toggle_btn.click()

    stored = page.evaluate(
        "id => localStorage.getItem('qm-server-collapsed-' + id)",
        server_id
    )
    assert stored == "0", f"Expected '0' in localStorage after expand, got {stored!r}"


@pytest.mark.e2e
def test_collapsed_state_restores_after_reload(page: Page):
    """Collapsing a server row and reloading must keep it collapsed."""
    _goto_containers(page)

    server_rows = page.locator("li[data-server-id]")
    server_rows.first.wait_for(state="attached", timeout=5000)

    if server_rows.count() == 0:
        pytest.skip("No server rows present — skipping persistence test.")

    first_row = server_rows.first
    server_id = first_row.get_attribute("data-server-id")

    toggle_btn = first_row.locator(".server-row-toggle")
    toggle_btn.click()

    assert first_row.evaluate("el => el.classList.contains('is-collapsed')"), \
        "Row must be collapsed before reload"

    page.reload()
    page.click("button.nav-item:has-text('Containers')")

    # Wait for server rows to load again via HTMX
    reloaded_row = page.locator(f'li[data-server-id="{server_id}"]')
    reloaded_row.wait_for(state="attached", timeout=5000)

    assert reloaded_row.evaluate("el => el.classList.contains('is-collapsed')"), \
        "Server row must still be collapsed after page reload"


@pytest.mark.e2e
def test_expanded_state_restores_after_reload(page: Page):
    """A server previously collapsed then expanded must stay expanded after reload."""
    _goto_containers(page)

    server_rows = page.locator("li[data-server-id]")
    server_rows.first.wait_for(state="attached", timeout=5000)

    if server_rows.count() == 0:
        pytest.skip("No server rows present — skipping persistence test.")

    first_row = server_rows.first
    server_id = first_row.get_attribute("data-server-id")
    toggle_btn = first_row.locator(".server-row-toggle")

    # Collapse then re-expand
    toggle_btn.click()
    toggle_btn.click()

    page.reload()
    page.click("button.nav-item:has-text('Containers')")

    reloaded_row = page.locator(f'li[data-server-id="{server_id}"]')
    reloaded_row.wait_for(state="attached", timeout=5000)

    assert not reloaded_row.evaluate("el => el.classList.contains('is-collapsed')"), \
        "Server row must be expanded after reload"
