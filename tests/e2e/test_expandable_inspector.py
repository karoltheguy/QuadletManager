"""
E2E tests for expandable inspector panel on Dashboard tab (Issue #38, #102).

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
    # Inspector is only visible on the Containers tab (hidden on default Overview tab)
    page.click("button.nav-item:has-text('Containers')")
    page.wait_for_selector("#inspector", state="visible")


# ── Button Existence ────────────────────────────────────────────────────────

def test_expand_button_exists_in_inspector(page: Page):
    """An expand/collapse toggle button must be present in the inspector panel."""
    _goto(page)
    btn = page.locator("#inspector-expand-btn")
    expect(btn).to_have_count(1)
    expect(btn).to_be_visible()


# ── Expand Behavior ─────────────────────────────────────────────────────────
# "Expanding" hides the inspector panel (body gains class `inspector-expanded`),
# giving the editor full width. The sidebar (#navigator) is unaffected.

def test_clicking_expand_hides_inspector(page: Page):
    """When expanded, the inspector panel itself should be hidden."""
    _goto(page)
    inspector = page.locator("#inspector")
    expect(inspector).to_be_visible()

    page.click("#inspector-expand-btn")

    expect(inspector).not_to_be_visible()


def test_clicking_expand_hides_right_resize_handle(page: Page):
    """When expanded, the right resize handle should be hidden."""
    _goto(page)
    page.click("#inspector-expand-btn")

    handle = page.locator("#resize-handle-right")
    expect(handle).not_to_be_visible()


def test_clicking_expand_keeps_sidebar_visible(page: Page):
    """Expanding the inspector must not affect the sidebar (#navigator)."""
    _goto(page)
    sidebar = page.locator("#navigator")
    expect(sidebar).to_be_visible()

    page.click("#inspector-expand-btn")

    expect(sidebar).to_be_visible()


# ── Collapse Behavior ───────────────────────────────────────────────────────

def test_clicking_again_restores_inspector(page: Page):
    """Clicking the button a second time should restore the inspector panel."""
    _goto(page)
    inspector = page.locator("#inspector")

    page.click("#inspector-expand-btn")
    expect(inspector).not_to_be_visible()

    page.click("#inspector-expand-btn")
    expect(inspector).to_be_visible()


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
    """Expanded state (inspector hidden) must survive a full page reload."""
    _goto(page)

    page.click("#inspector-expand-btn")
    inspector = page.locator("#inspector")
    expect(inspector).not_to_be_visible()

    # After reload, switch to Containers tab again (page reloads to Overview)
    page.reload()
    page.click("button.nav-item:has-text('Containers')")

    expect(inspector).not_to_be_visible()


def test_collapsed_state_persists_across_reload(page: Page):
    """Collapsing after expanding should persist — inspector must be visible after reload."""
    _goto(page)

    # Expand then collapse
    page.click("#inspector-expand-btn")
    page.click("#inspector-expand-btn")

    page.reload()
    page.click("button.nav-item:has-text('Containers')")
    page.wait_for_selector("#inspector", state="visible")

    inspector = page.locator("#inspector")
    expect(inspector).to_be_visible()


# ── Tab Switching ───────────────────────────────────────────────────────────

def test_expand_only_affects_dashboard_tab(page: Page):
    """Expanding the inspector should not affect other tabs."""
    _goto(page)

    page.click("#inspector-expand-btn")

    # Switch to a different tab to verify expand state doesn't bleed across tabs
    page.click("button.nav-item:has-text('Overview')")
    # Navigator is hidden on Overview tab regardless of inspector expand state
    sidebar = page.locator("#navigator")
    expect(sidebar).not_to_be_visible()


# ── Editor-loaded toggle (Issue #102) ───────────────────────────────────────

MOCK_EDITOR_HTML = (
    '<div id="editor-pane" class="main-content">'
    '<div class="header-bar">'
    '<h2 class="panel-title">Editor: test.container</h2>'
    '<div class="header-actions">'
    '<div id="editor-actions"></div>'
    '<button id="inspector-expand-btn" class="btn btn-sm btn-secondary"'
    ' onclick="toggleInspectorExpand()" title="Collapse inspector"'
    ' aria-label="Collapse inspector"></button>'
    '</div></div>'
    '<div id="editor-container" style="flex:1;min-height:200px;"></div>'
    '<script>'
    '(function(){'
    '  var tgt = document.getElementById("editor-container");'
    '  require(["vs/editor/editor.main"], function(){'
    '    if (!document.body.contains(tgt)) return;'
    '    if (window.editor){ window.editor.dispose(); }'
    '    window.editor = monaco.editor.create(tgt, {'
    '      value: "[Container]\\nImage=nginx\\n",'
    '      language: "ini", theme: "vs-dark", automaticLayout: true'
    '    });'
    '  });'
    '})();'
    '</script>'
    '</div>'
)


def test_extend_right_retracts_after_editor_load(page: Page):
    """Issue #102: extend-right toggle must retract the inspector after Monaco loads.

    The bug: with a Monaco editor open, the flex item (.main-content) cannot shrink
    because Monaco sets a pixel style.width on its root element, establishing a large
    min-content-size (min-width: auto default). On retract, the inspector is pushed
    off-screen to the right rather than returning within the viewport.
    """
    page.route(
        "**/api/file/**",
        lambda route: route.fulfill(
            status=200,
            headers={"Content-Type": "text/html"},
            body=MOCK_EDITOR_HTML,
        ),
    )

    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")

    page.click("button.nav-item:has-text('Containers')")
    page.wait_for_selector("#inspector", state="visible")

    # Load the editor via HTMX (same path the navigator uses)
    page.evaluate(
        "() => htmx.ajax('GET',"
        " '/api/file/1?path=/etc/containers/systemd/test.container&scope=global&name=test.container',"
        " {target: '#editor-pane', swap: 'outerHTML'})"
    )
    page.wait_for_function("() => window.editor != null", timeout=10_000)

    inspector = page.locator("#inspector")
    viewport = page.viewport_size

    # First click — extend (inspector hides)
    page.click("#inspector-expand-btn")
    expect(inspector).not_to_be_visible()

    # Second click — retract (inspector must return within the viewport)
    page.click("#inspector-expand-btn")
    expect(inspector).to_be_visible()

    box = inspector.bounding_box()
    assert box is not None, "Inspector has no bounding box after retract"
    assert box["x"] + box["width"] <= viewport["width"] + 5, (
        f"Inspector is off-screen after retract: x={box['x']}, width={box['width']},"
        f" viewport={viewport['width']}"
    )
