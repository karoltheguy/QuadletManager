"""
E2E tests for collapsible server rows with chevron and keyboard nav (Issue #114).

Requires the backend running on localhost:8000 and Playwright installed.
Run with: pytest tests/e2e/test_server_collapse_e2e.py
"""
import pytest

try:
    from playwright.sync_api import Page, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Page = typing.Any
    def expect(x: typing.Any) -> typing.Any: pass

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="Playwright is not installed in this environment"
)

BASE_URL = "http://localhost:8000"


def _goto(page: Page):
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")
    page.click("button.nav-item:has-text('Containers')")
    page.wait_for_selector(".server-row-toggle", timeout=5000)


# ── Structure ────────────────────────────────────────────────────────────────

def test_server_row_toggle_button_exists(page: Page):
    _goto(page)
    toggles = page.locator(".server-row-toggle")
    assert toggles.count() >= 1, "Expected at least one .server-row-toggle button"


def test_server_chevron_exists(page: Page):
    _goto(page)
    chevrons = page.locator(".server-chevron")
    assert chevrons.count() >= 1, "Expected at least one .server-chevron span"


def test_server_quadlet_tree_class_exists(page: Page):
    _goto(page)
    trees = page.locator(".server-quadlet-tree")
    assert trees.count() >= 1, "Expected at least one .server-quadlet-tree div"


def test_toggle_button_is_focusable(page: Page):
    _goto(page)
    toggle = page.locator(".server-row-toggle").first
    expect(toggle).to_be_visible()
    toggle.focus()
    focused = page.evaluate("document.activeElement.classList.contains('server-row-toggle')")
    assert focused, "server-row-toggle should be focusable"


# ── Collapse / Expand ────────────────────────────────────────────────────────

def test_click_collapses_server(page: Page):
    _goto(page)
    toggle = page.locator(".server-row-toggle").first
    li = page.locator("li[data-server-id]").first
    toggle.click()
    expect(li).to_have_class("is-collapsed")


def test_click_again_expands_server(page: Page):
    _goto(page)
    toggle = page.locator(".server-row-toggle").first
    li = page.locator("li[data-server-id]").first
    toggle.click()
    toggle.click()
    classes = li.get_attribute("class") or ""
    assert "is-collapsed" not in classes, "Second click should remove is-collapsed"


def test_collapse_hides_quadlet_tree(page: Page):
    _goto(page)
    toggle = page.locator(".server-row-toggle").first
    tree = page.locator(".server-quadlet-tree").first
    toggle.click()
    expect(tree).to_be_hidden()


def test_expand_shows_quadlet_tree(page: Page):
    _goto(page)
    toggle = page.locator(".server-row-toggle").first
    tree = page.locator(".server-quadlet-tree").first
    toggle.click()
    toggle.click()
    expect(tree).to_be_visible()


# ── aria-expanded ────────────────────────────────────────────────────────────

def test_aria_expanded_starts_true(page: Page):
    _goto(page)
    toggle = page.locator(".server-row-toggle").first
    expect(toggle).to_have_attribute("aria-expanded", "true")


def test_aria_expanded_false_when_collapsed(page: Page):
    _goto(page)
    toggle = page.locator(".server-row-toggle").first
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "false")


def test_aria_expanded_true_after_reexpand(page: Page):
    _goto(page)
    toggle = page.locator(".server-row-toggle").first
    toggle.click()
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")


# ── + Button Independence ────────────────────────────────────────────────────

def test_new_btn_does_not_collapse(page: Page):
    _goto(page)
    li = page.locator("li[data-server-id]").first
    new_btn = li.locator(".server-new-btn")
    if new_btn.count() == 0:
        pytest.skip("No .server-new-btn visible (viewer role?)")
    new_btn.click()
    # Close any modal that may open
    page.keyboard.press("Escape")
    classes = li.get_attribute("class") or ""
    assert "is-collapsed" not in classes, "+ button should not trigger collapse"


# ── Keyboard Navigation ──────────────────────────────────────────────────────

def test_arrow_left_collapses(page: Page):
    _goto(page)
    toggle = page.locator(".server-row-toggle").first
    li = page.locator("li[data-server-id]").first
    toggle.focus()
    page.keyboard.press("ArrowLeft")
    expect(li).to_have_class("is-collapsed")


def test_arrow_right_expands(page: Page):
    _goto(page)
    toggle = page.locator(".server-row-toggle").first
    li = page.locator("li[data-server-id]").first
    toggle.focus()
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowRight")
    classes = li.get_attribute("class") or ""
    assert "is-collapsed" not in classes


def test_enter_toggles_collapse(page: Page):
    _goto(page)
    toggle = page.locator(".server-row-toggle").first
    li = page.locator("li[data-server-id]").first
    toggle.focus()
    page.keyboard.press("Enter")
    expect(li).to_have_class("is-collapsed")


def test_space_toggles_collapse(page: Page):
    _goto(page)
    toggle = page.locator(".server-row-toggle").first
    li = page.locator("li[data-server-id]").first
    toggle.focus()
    page.keyboard.press("Space")
    expect(li).to_have_class("is-collapsed")
