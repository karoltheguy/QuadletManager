"""
Characterization/regression guard for the role-based locator fix (Issue
#234).

This is NOT a red test: it passes on arrival. `get_by_role` already excludes
elements that are not exposed in the accessibility tree, and a `display:none`
element (such as the hidden per-row "Save" button inside
`<tr id="server-edit-row-N" style="display:none">` in `#servers-list`) is
never exposed there. So `page.locator("#settings-pane").get_by_role("button",
name="Add Server")` already resolves unambiguously to the visible "Add
Server" button today, with no code change required.

Its value going forward is as a regression guard: it will fail if a second
visible "Add Server"-named control is ever introduced into `#settings-pane`,
or if the "Add Server" button's accessible name is ever lost or changed
(e.g. by removing its visible text without providing an aria-label).
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

from tests.app_url import BASE_URL


@pytest.mark.e2e
def test_add_server_button_resolves_unambiguously_via_get_by_role(page: Page):
    """The hidden per-row 'Save' button inside a server edit row precedes
    the visible 'Add Server' button in DOM order, so a CSS-class selector
    like '#settings-pane .btn-primary' is ambiguous. A role-based locator
    must resolve to exactly the visible 'Add Server' button instead."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip(f"Backend is not running on {BASE_URL} — skipping E2E tests.")

    page.click("button.nav-item:has-text('Settings')")
    expect(page.locator("#settings-pane")).to_be_visible()

    # The hidden edit row is rendered by an htmx-loaded servers list, not
    # present in the initial HTML. Wait for it to be attached before
    # asserting the hazard below, otherwise the hazard assertion would be
    # checking a locator that doesn't exist yet (a vacuous pass).
    expect(
        page.locator("#servers-list tr[id^='server-edit-row-']").first
    ).to_be_attached(timeout=10000)

    # ── Assert the hazard is real ──
    # The first '.btn-primary' in DOM order under #settings-pane is the
    # hidden per-row Save button, and it must never become visible.
    hidden_save_button = page.locator("#settings-pane .btn-primary").first
    expect(hidden_save_button).to_be_hidden()

    # ── Assert the fix works ──
    # get_by_role("button", name="Add Server") only matches elements
    # exposed in the accessibility tree. display:none elements (like the
    # hidden per-row Save button above) are excluded from that tree
    # entirely, so this locator resolves unambiguously to the single
    # visible "Add Server" button, with no container-scoping workaround
    # needed.
    add_server_button = page.locator("#settings-pane").get_by_role(
        "button", name="Add Server"
    )
    expect(add_server_button).to_have_count(1)
    expect(add_server_button).to_be_visible()
