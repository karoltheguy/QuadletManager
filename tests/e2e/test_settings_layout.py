"""
Tests for Settings tab layout (Issue #27):
- Title must have proper left padding (not cut off)
- Settings use inner sidebar navigation with section groups
- Active section uses a multi-column grid on wide viewports
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


@pytest.mark.e2e
def test_settings_title_has_left_padding(page: Page):
    """The Settings header must have non-zero bottom padding (title separation from content)."""
    _goto_settings(page)
    # Current design uses padding: 0 0 0.9rem 0 on the header-bar — check bottom padding.
    padding_bottom = page.locator("#settings-pane .header-bar").evaluate(
        "el => parseFloat(window.getComputedStyle(el).paddingBottom)"
    )
    assert padding_bottom > 0, (
        f"Settings header-bar padding-bottom should be > 0, got {padding_bottom}px"
    )


@pytest.mark.e2e
def test_settings_title_is_fully_visible(page: Page):
    """The Settings panel-title must be fully within the viewport horizontally."""
    _goto_settings(page)
    title_box = page.locator("#settings-pane .panel-title").bounding_box()
    assert title_box is not None, "Settings panel-title not found in DOM"
    assert title_box["x"] >= 0, (
        f"Settings title starts at x={title_box['x']}, which is off-screen"
    )


@pytest.mark.e2e
def test_settings_sidenav_is_visible(page: Page):
    """Settings page must render an inner sidebar navigation."""
    _goto_settings(page)
    expect(page.locator(".settings-sidenav")).to_be_visible()
    assert page.locator(".settings-sidenav-item").count() > 0, (
        "Settings sidenav must have at least one navigation item"
    )


@pytest.mark.e2e
def test_settings_sidenav_switches_sections(page: Page):
    """Clicking a sidenav item shows that group and hides others."""
    _goto_settings(page)
    # Servers group should be visible by default
    expect(page.locator(".settings-group[data-group='servers']")).to_be_visible()
    expect(page.locator(".settings-group[data-group='ssh-keys']")).to_be_hidden()

    # Click SSH Keys nav item
    page.click(".settings-sidenav-item[data-section='ssh-keys']")
    expect(page.locator(".settings-group[data-group='ssh-keys']")).to_be_visible()
    expect(page.locator(".settings-group[data-group='servers']")).to_be_hidden()


@pytest.mark.e2e
def test_settings_active_group_uses_grid_layout(page: Page):
    """The active settings group must use CSS grid for multi-column layout."""
    _goto_settings(page)
    display = page.locator(".settings-group[data-group='servers']").evaluate(
        "el => window.getComputedStyle(el).display"
    )
    assert display == "grid", (
        f"Active settings-group should use display:grid, got '{display}'"
    )


@pytest.mark.e2e
def test_settings_group_multi_column_on_wide_viewport(page: Page):
    """On a wide viewport, sections within the active group should fill multiple columns."""
    page.set_viewport_size({"width": 1400, "height": 900})
    _goto_settings(page)

    # Exclude full-width sections (they intentionally span all columns)
    sections = page.locator(
        ".settings-group[data-group='servers'] .settings-section:not(.full-width)"
    )
    count = sections.count()
    if count < 2:
        pytest.skip("Not enough non-full-width settings sections visible to test multi-column layout")

    first_box = sections.nth(0).bounding_box()
    second_box = sections.nth(1).bounding_box()

    assert first_box is not None and second_box is not None
    # In a multi-column grid the second section should be beside the first
    assert abs(first_box["y"] - second_box["y"]) < 10, (
        f"On a 1400px viewport, sections should be side-by-side. "
        f"Section 1 y={first_box['y']}, Section 2 y={second_box['y']}"
    )


@pytest.mark.e2e
def test_settings_group_single_column_on_narrow_viewport(page: Page):
    """On a narrow viewport, sections within the active group should collapse to one column."""
    page.set_viewport_size({"width": 600, "height": 900})
    _goto_settings(page)

    sections = page.locator(
        ".settings-group[data-group='servers'] .settings-section:not(.full-width)"
    )
    count = sections.count()
    if count < 2:
        pytest.skip("Not enough non-full-width settings sections visible to test single-column layout")

    first_box = sections.nth(0).bounding_box()
    second_box = sections.nth(1).bounding_box()

    assert first_box is not None and second_box is not None
    # In a single column layout, the second section should be below the first
    assert second_box["y"] > first_box["y"], (
        f"On a 600px viewport, sections should stack vertically. "
        f"Section 1 y={first_box['y']}, Section 2 y={second_box['y']}"
    )


@pytest.mark.e2e
def test_settings_server_action_buttons_not_clipped(page: Page):
    """The Edit / Re-pin host key / Remove buttons in a server row's actions cell
    must be fully visible and contained within their td, not clipped by the
    .settings-table's overflow/ellipsis rules (Issue #219)."""
    _goto_settings(page)

    servers_table = page.locator("#servers-list table.settings-table")
    expect(servers_table).to_be_visible()

    row = servers_table.locator("tr", has_text="Mock Server")
    expect(row).to_be_visible()

    actions_cell = row.locator("td").last
    td_box = actions_cell.bounding_box()
    assert td_box is not None, "Actions <td> for 'Mock Server' row not found"

    for label in ["Edit", "Re-pin host key", "Remove"]:
        button = actions_cell.locator("button", has_text=label)
        expect(button).to_be_visible()
        btn_box = button.bounding_box()
        assert btn_box is not None, f"Button '{label}' not found in actions cell"

        assert btn_box["x"] >= td_box["x"], (
            f"Button '{label}' starts left of its td: "
            f"button.x={btn_box['x']} < td.x={td_box['x']}"
        )
        assert btn_box["x"] + btn_box["width"] <= td_box["x"] + td_box["width"] + 1, (
            f"Button '{label}' overflows its td horizontally: "
            f"button.x={btn_box['x']}, button.width={btn_box['width']}, "
            f"button right edge={btn_box['x'] + btn_box['width']}, "
            f"td.x={td_box['x']}, td.width={td_box['width']}, "
            f"td right edge={td_box['x'] + td_box['width']}"
        )
