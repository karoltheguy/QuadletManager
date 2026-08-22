"""
E2E tests for resizable panel handles (Issue #12).

Requires the backend running on localhost:8000 and Playwright installed.
Run with: pytest tests/test_resizable_panels.py
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
    # Navigator and resize handles are only visible on the Containers tab
    page.click("button.nav-item:has-text('Containers')")


# ── Existence Tests ──────────────────────────────────────────────────────────

@pytest.mark.e2e
def test_resize_handles_exist(page: Page):
    """Both resize-handle dividers must be present in the DOM."""
    _goto(page)
    left = page.locator("#resize-handle-left")
    right = page.locator("#resize-handle-right")
    expect(left).to_have_count(1)
    expect(right).to_have_count(1)


@pytest.mark.e2e
def test_resize_handles_have_correct_cursor(page: Page):
    """Handles must advertise col-resize cursor via CSS."""
    _goto(page)
    for handle_id in ("#resize-handle-left", "#resize-handle-right"):
        cursor = page.eval_on_selector(
            handle_id,
            "el => getComputedStyle(el).cursor"
        )
        assert cursor == "col-resize", (
            f"{handle_id} cursor should be 'col-resize', got '{cursor}'"
        )


# ── Drag Tests ───────────────────────────────────────────────────────────────

@pytest.mark.e2e
def test_drag_left_handle_widens_sidebar(page: Page):
    """Dragging the left handle to the right should widen the sidebar."""
    _goto(page)

    sidebar = page.locator("#navigator")
    handle = page.locator("#resize-handle-left")

    initial_width = sidebar.bounding_box()["width"]

    # Drag the handle 80px to the right
    handle_box = handle.bounding_box()
    start_x = handle_box["x"] + handle_box["width"] / 2
    start_y = handle_box["y"] + handle_box["height"] / 2

    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x + 80, start_y, steps=10)
    page.mouse.up()

    final_width = sidebar.bounding_box()["width"]
    assert final_width > initial_width, (
        f"Sidebar should have grown after right-drag: {initial_width} → {final_width}"
    )


@pytest.mark.e2e
def test_drag_left_handle_narrows_sidebar(page: Page):
    """Dragging the left handle to the left should narrow the sidebar."""
    _goto(page)

    sidebar = page.locator("#navigator")
    handle = page.locator("#resize-handle-left")

    initial_width = sidebar.bounding_box()["width"]

    handle_box = handle.bounding_box()
    start_x = handle_box["x"] + handle_box["width"] / 2
    start_y = handle_box["y"] + handle_box["height"] / 2

    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x - 60, start_y, steps=10)
    page.mouse.up()

    final_width = sidebar.bounding_box()["width"]
    assert final_width < initial_width, (
        f"Sidebar should have shrunk after left-drag: {initial_width} → {final_width}"
    )


@pytest.mark.skip(reason="Right handle is currently hidden in all views")
@pytest.mark.e2e
def test_drag_right_handle_widens_inspector(page: Page):
    """Dragging the right handle to the left should widen the inspector."""
    _goto(page)

    inspector = page.locator("#inspector")
    handle = page.locator("#resize-handle-right")

    initial_width = inspector.bounding_box()["width"]

    handle_box = handle.bounding_box()
    start_x = handle_box["x"] + handle_box["width"] / 2
    start_y = handle_box["y"] + handle_box["height"] / 2

    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x - 80, start_y, steps=10)  # left = wider inspector
    page.mouse.up()

    final_width = inspector.bounding_box()["width"]
    assert final_width > initial_width, (
        f"Inspector should have grown after left-drag: {initial_width} → {final_width}"
    )


# ── Min/Max Clamp Tests ──────────────────────────────────────────────────────

@pytest.mark.e2e
def test_sidebar_respects_minimum_width(page: Page):
    """Sidebar must not shrink below 180 px regardless of drag distance."""
    _goto(page)

    handle = page.locator("#resize-handle-left")
    sidebar = page.locator("#navigator")

    handle_box = handle.bounding_box()
    start_x = handle_box["x"] + handle_box["width"] / 2
    start_y = handle_box["y"] + handle_box["height"] / 2

    # Drag far to the left (way past the minimum)
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(10, start_y, steps=20)
    page.mouse.up()

    final_width = sidebar.bounding_box()["width"]
    assert final_width >= 180, (
        f"Sidebar width {final_width}px is below the 180px minimum"
    )


@pytest.mark.skip(reason="Right handle is currently hidden in all views")
@pytest.mark.e2e
def test_inspector_respects_minimum_width(page: Page):
    """Inspector must not shrink below 220 px regardless of drag distance."""
    _goto(page)

    handle = page.locator("#resize-handle-right")
    inspector = page.locator("#inspector")

    handle_box = handle.bounding_box()
    start_x = handle_box["x"] + handle_box["width"] / 2
    start_y = handle_box["y"] + handle_box["height"] / 2

    # Drag far to the right (narrowing the inspector past its minimum)
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x + 2000, start_y, steps=20)
    page.mouse.up()

    final_width = inspector.bounding_box()["width"]
    assert final_width >= 220, (
        f"Inspector width {final_width}px is below the 220px minimum"
    )


# ── localStorage Persistence ─────────────────────────────────────────────────

@pytest.mark.e2e
def test_sidebar_width_persists_across_reload(page: Page):
    """Width set by dragging must survive a full page reload."""
    _goto(page)

    handle = page.locator("#resize-handle-left")
    sidebar = page.locator("#navigator")

    handle_box = handle.bounding_box()
    start_x = handle_box["x"] + handle_box["width"] / 2
    start_y = handle_box["y"] + handle_box["height"] / 2

    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x + 80, start_y, steps=10)
    page.mouse.up()

    width_after_drag = sidebar.bounding_box()["width"]

    page.reload()

    # After reload the page returns to Overview tab; navigate back to Containers
    # so #navigator is visible before reading its width
    page.click("button.nav-item:has-text('Containers')")
    page.wait_for_selector("#navigator", state="visible")

    width_after_reload = sidebar.bounding_box()["width"]
    assert abs(width_after_reload - width_after_drag) < 2, (
        f"Sidebar width not persisted: dragged={width_after_drag}, "
        f"after reload={width_after_reload}"
    )
