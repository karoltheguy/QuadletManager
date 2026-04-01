"""
Tests for Settings tab layout fixes (Issue #27):
- Title must have proper left padding (not cut off)
- Content must use a multi-column grid on wide viewports
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


def _goto_settings(page: Page):
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")
    page.click("button.nav-item:has-text('Settings')")
    expect(page.locator("#settings-pane")).to_be_visible()


def test_settings_title_has_left_padding(page: Page):
    """The Settings header must have non-zero padding-left so the title is not cut off."""
    _goto_settings(page)
    padding_left = page.locator("#settings-pane .header-bar").evaluate(
        "el => parseFloat(window.getComputedStyle(el).paddingLeft)"
    )
    assert padding_left > 0, (
        f"Settings header-bar padding-left should be > 0, got {padding_left}px"
    )


def test_settings_title_is_fully_visible(page: Page):
    """The Settings panel-title must be fully within the viewport horizontally."""
    _goto_settings(page)
    title_box = page.locator("#settings-pane .panel-title").bounding_box()
    assert title_box is not None, "Settings panel-title not found in DOM"
    assert title_box["x"] >= 0, (
        f"Settings title starts at x={title_box['x']}, which is off-screen"
    )


def test_settings_content_uses_grid_layout(page: Page):
    """settings-content must use CSS grid (not flexbox) for the multi-column layout."""
    _goto_settings(page)
    display = page.locator(".settings-content").evaluate(
        "el => window.getComputedStyle(el).display"
    )
    assert display == "grid", (
        f"settings-content should use display:grid, got '{display}'"
    )


def test_settings_content_multi_column_on_wide_viewport(page: Page):
    """On a wide viewport, settings sections should fill multiple columns."""
    page.set_viewport_size({"width": 1400, "height": 900})
    _goto_settings(page)

    sections = page.locator(".settings-section")
    count = sections.count()
    if count < 2:
        pytest.skip("Not enough settings sections visible to test multi-column layout")

    first_box = sections.nth(0).bounding_box()
    second_box = sections.nth(1).bounding_box()

    assert first_box is not None and second_box is not None
    # In a multi-column grid the second section should be beside (same row) the first,
    # meaning their top Y positions are approximately equal.
    assert abs(first_box["y"] - second_box["y"]) < 10, (
        f"On a 1400px viewport, sections should be side-by-side. "
        f"Section 1 y={first_box['y']}, Section 2 y={second_box['y']}"
    )


def test_settings_content_single_column_on_narrow_viewport(page: Page):
    """On a narrow viewport, settings sections should collapse to a single column."""
    page.set_viewport_size({"width": 600, "height": 900})
    _goto_settings(page)

    sections = page.locator(".settings-section")
    count = sections.count()
    if count < 2:
        pytest.skip("Not enough settings sections visible to test single-column layout")

    first_box = sections.nth(0).bounding_box()
    second_box = sections.nth(1).bounding_box()

    assert first_box is not None and second_box is not None
    # In a single column layout, the second section should be below the first.
    assert second_box["y"] > first_box["y"], (
        f"On a 600px viewport, sections should stack vertically. "
        f"Section 1 y={first_box['y']}, Section 2 y={second_box['y']}"
    )
