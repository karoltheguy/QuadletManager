"""
E2E tests for expandable inspector panel on Dashboard tab (Issue #38).

Requires the backend running on localhost:8000 and Playwright installed.
Run with: pytest tests/test_expandable_inspector.py
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

BASE_URL = "http://localhost:8000"


def _goto(page: Page):
    """Navigate to the dashboard, skip test if backend is not running."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")
    # Ensure we're on the dashboard tab
    page.wait_for_selector("#inspector", state="visible")


# ── Button Existence ────────────────────────────────────────────────────────

def test_expand_button_exists_in_inspector(page: Page):
    """An expand/collapse toggle button must be present in the inspector panel."""
    _goto(page)
    btn = page.locator("#inspector-expand-btn")
    expect(btn).to_have_count(1)
    expect(btn).to_be_visible()


# ── Expand Behavior ─────────────────────────────────────────────────────────

def test_clicking_expand_hides_sidebar(page: Page):
    """When expanded, the sidebar should be hidden."""
    _goto(page)
    sidebar = page.locator("#navigator")
    expect(sidebar).to_be_visible()

    page.click("#inspector-expand-btn")

    expect(sidebar).not_to_be_visible()


def test_clicking_expand_hides_resize_handle(page: Page):
    """When expanded, the left resize handle should be hidden."""
    _goto(page)
    handle = page.locator("#resize-handle-left")
    expect(handle).to_be_visible()

    page.click("#inspector-expand-btn")

    expect(handle).not_to_be_visible()


def test_inspector_fills_full_width_when_expanded(page: Page):
    """When expanded, the inspector should fill the full app-container width."""
    _goto(page)
    inspector = page.locator("#inspector")
    container = page.locator(".app-container")

    initial_width = inspector.bounding_box()["width"]
    page.click("#inspector-expand-btn")

    expanded_width = inspector.bounding_box()["width"]
    container_width = container.bounding_box()["width"]

    assert expanded_width > initial_width, (
        f"Inspector should be wider when expanded: {initial_width} → {expanded_width}"
    )
    # Allow a small tolerance for borders
    assert abs(expanded_width - container_width) < 5, (
        f"Inspector should fill container: inspector={expanded_width}, container={container_width}"
    )


# ── Collapse Behavior ───────────────────────────────────────────────────────

def test_clicking_again_restores_sidebar(page: Page):
    """Clicking the button a second time should restore the sidebar."""
    _goto(page)
    sidebar = page.locator("#navigator")

    page.click("#inspector-expand-btn")
    expect(sidebar).not_to_be_visible()

    page.click("#inspector-expand-btn")
    expect(sidebar).to_be_visible()


def test_inspector_restores_original_width(page: Page):
    """After collapse, the inspector should return to its previous width."""
    _goto(page)
    inspector = page.locator("#inspector")
    initial_width = inspector.bounding_box()["width"]

    page.click("#inspector-expand-btn")
    page.click("#inspector-expand-btn")

    restored_width = inspector.bounding_box()["width"]
    assert abs(restored_width - initial_width) < 5, (
        f"Inspector width not restored: initial={initial_width}, restored={restored_width}"
    )


# ── localStorage Persistence ────────────────────────────────────────────────

def test_expanded_state_persists_across_reload(page: Page):
    """Expanded state must survive a full page reload."""
    _goto(page)

    page.click("#inspector-expand-btn")
    sidebar = page.locator("#navigator")
    expect(sidebar).not_to_be_visible()

    page.reload()
    page.wait_for_selector("#inspector", state="visible")

    expect(sidebar).not_to_be_visible()


def test_collapsed_state_persists_across_reload(page: Page):
    """Collapsing after expanding should persist the collapsed state."""
    _goto(page)

    # Expand then collapse
    page.click("#inspector-expand-btn")
    page.click("#inspector-expand-btn")

    page.reload()
    page.wait_for_selector("#inspector", state="visible")

    sidebar = page.locator("#navigator")
    expect(sidebar).to_be_visible()


# ── Tab Switching ───────────────────────────────────────────────────────────

def test_expand_only_affects_dashboard_tab(page: Page):
    """Expanding the inspector should not affect other tabs."""
    _goto(page)

    page.click("#inspector-expand-btn")

    # Switch to editor tab
    page.click("text=Editor")
    # Sidebar should be visible on editor tab (editor view shows sidebar)
    sidebar = page.locator("#navigator")
    expect(sidebar).to_be_visible()
