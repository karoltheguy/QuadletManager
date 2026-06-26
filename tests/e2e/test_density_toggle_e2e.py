"""
E2E tests for UI Density toggle (Issue #109).
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

BASE_URL = "http://localhost:8000"


def _goto_density(page: Page):
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")
    page.click("button.nav-item:has-text('Settings')")
    expect(page.locator("#settings-pane")).to_be_visible()
    page.click(".settings-sidenav-item[data-section='themes']")
    expect(page.locator("#density-section")).to_be_visible()


@pytest.mark.e2e
def test_density_section_visible_in_themes_tab(page: Page):
    """Themes settings tab must show the density toggle section."""
    _goto_density(page)
    expect(page.locator("#density-section")).to_be_visible()
    expect(page.locator("#density-relaxed")).to_be_visible()
    expect(page.locator("#density-compact")).to_be_visible()


@pytest.mark.e2e
def test_compact_toggle_sets_data_attribute(page: Page):
    """Selecting Compact must set data-density='compact' on <html>."""
    _goto_density(page)
    page.locator("#density-compact").check()
    density = page.evaluate(
        "document.documentElement.getAttribute('data-density')"
    )
    assert density == "compact", f"Expected data-density='compact', got {density!r}"


@pytest.mark.e2e
def test_relaxed_toggle_removes_data_attribute(page: Page):
    """Selecting Relaxed must remove data-density from <html>."""
    _goto_density(page)
    page.locator("#density-compact").check()
    page.locator("#density-relaxed").check()
    density = page.evaluate(
        "document.documentElement.getAttribute('data-density')"
    )
    assert density is None or density == "", (
        f"Expected no data-density after Relaxed, got {density!r}"
    )


@pytest.mark.e2e
def test_compact_persists_in_localstorage(page: Page):
    """Selecting Compact must write 'compact' to localStorage['qm-density']."""
    _goto_density(page)
    page.locator("#density-compact").check()
    stored = page.evaluate("localStorage.getItem('qm-density')")
    assert stored == "compact", f"Expected qm-density='compact' in localStorage, got {stored!r}"


@pytest.mark.e2e
def test_density_fouc_prevention_on_reload(page: Page):
    """data-density must be applied before first paint (no FOUC) after page reload."""
    _goto_density(page)
    page.locator("#density-compact").check()
    page.reload()
    density = page.evaluate(
        "document.documentElement.getAttribute('data-density')"
    )
    assert density == "compact", (
        f"Expected data-density='compact' immediately after reload, got {density!r}"
    )
    # Cleanup
    page.evaluate("localStorage.removeItem('qm-density')")
