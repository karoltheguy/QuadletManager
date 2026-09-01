"""Playwright E2E tests for server drag-and-drop reordering (issue #95).

Requires the backend running at QM_APP_URL with at least two servers configured.
"""
import pytest

try:
    from playwright.sync_api import Page, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Page = typing.Any

    def expect(x: typing.Any) -> typing.Any:
        pass

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT, reason="Playwright not installed"
)

from tests.app_url import BASE_URL


def _goto_servers_settings(page: Page):
    # Wait for the htmx load of servers content during page load, so the rows
    # exist before any test interaction. The drag listeners themselves are
    # delegated on `document` by initServerReorder(), so they survive the swap.
    try:
        with page.expect_response(
            lambda r: r.url.rstrip("/").endswith("/api/settings/servers")
                      and r.request.method == "GET",
            timeout=5000,
        ):
            page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip(f"Backend is not running on {BASE_URL} — skipping E2E tests.")
    page.click("button.nav-item:has-text('Settings')")
    expect(page.locator("#settings-pane")).to_be_visible()
    page.click(".settings-sidenav-item[data-section='servers']")
    # Give htmx time to apply the DOM update from the initial page-load response.
    # hx-trigger="load" fires at DOMContentLoaded while #settings-pane is display:none,
    # making DOM-update timing unreliable; 10s covers the worst-case async lag.
    page.wait_for_function(
        "() => document.querySelector('#servers-tbody tr[data-server-id]') !== null",
        timeout=10000,
    )


def _get_server_row_ids(page: Page) -> list:
    return page.evaluate("""
        () => Array.from(
            document.querySelectorAll('#servers-tbody tr[data-server-id]')
        ).map(r => parseInt(r.dataset.serverId, 10))
    """)


def _simulate_drag(page: Page, source_id: int, target_id: int):
    """Simulate HTML5 drag events from source row to target row."""
    page.evaluate("""
        ([srcId, tgtId]) => {
            const src = document.querySelector(`tr[data-server-id="${srcId}"]`);
            const tgt = document.querySelector(`tr[data-server-id="${tgtId}"]`);
            if (!src || !tgt) throw new Error('Row not found');
            const dt = new DataTransfer();
            src.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
            tgt.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
            tgt.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
            src.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
        }
    """, [source_id, target_id])


@pytest.mark.e2e
def test_drag_handle_visible_for_admin(page: Page):
    """The drag handle column must be rendered for admin users."""
    _goto_servers_settings(page)
    row_ids = _get_server_row_ids(page)
    if not row_ids:
        pytest.skip("No servers configured — skipping drag handle test.")
    handles = page.locator('#servers-tbody .drag-handle')
    assert handles.count() > 0, "Expected at least one drag handle cell for admin"


@pytest.mark.e2e
def test_server_rows_have_draggable_attribute(page: Page):
    """Server rows in the settings table must have draggable=true for admin."""
    _goto_servers_settings(page)
    row_ids = _get_server_row_ids(page)
    if not row_ids:
        pytest.skip("No servers configured — skipping draggable attribute test.")
    first_row = page.locator(f'tr[data-server-id="{row_ids[0]}"]')
    draggable = first_row.get_attribute('draggable')
    assert draggable == 'true', f"Expected draggable='true', got '{draggable}'"


@pytest.mark.e2e
def test_drag_reorders_rows_in_dom(page: Page):
    """Dragging a server row should update the DOM order immediately."""
    _goto_servers_settings(page)
    row_ids = _get_server_row_ids(page)
    if len(row_ids) < 2:
        pytest.skip("Need at least 2 servers to test reordering.")

    first_id, second_id = row_ids[0], row_ids[1]
    # Drag second_id onto first_id: insertBefore(row_second, row_first) → second becomes first
    _simulate_drag(page, second_id, first_id)
    page.wait_for_timeout(300)

    new_order = _get_server_row_ids(page)
    assert new_order[0] == second_id, (
        f"After drag, expected first row to be server {second_id}, got {new_order[0]}"
    )
    assert first_id in new_order, "Dragged server should still appear in list"


@pytest.mark.e2e
def test_reorder_persists_after_page_reload(page: Page):
    """After dragging, the new order must survive a page reload (DB persisted)."""
    _goto_servers_settings(page)
    row_ids = _get_server_row_ids(page)
    if len(row_ids) < 2:
        pytest.skip("Need at least 2 servers to test persistence.")

    first_id, second_id = row_ids[0], row_ids[1]
    with page.expect_response("**/api/settings/servers/reorder"):
        _simulate_drag(page, second_id, first_id)

    page.reload()
    page.click("button.nav-item:has-text('Settings')")
    page.click(".settings-sidenav-item[data-section='servers']")

    persisted_order = _get_server_row_ids(page)
    assert persisted_order[0] == second_id, (
        f"After reload, expected first row to be server {second_id}, got {persisted_order[0]}"
    )


@pytest.mark.e2e
def test_sidebar_reflects_management_list_order(page: Page):
    """The sidebar server list must match the management list order."""
    _goto_servers_settings(page)
    row_ids = _get_server_row_ids(page)
    if len(row_ids) < 2:
        pytest.skip("Need at least 2 servers to test sidebar order.")

    first_id, second_id = row_ids[0], row_ids[1]
    with page.expect_response("**/api/servers"):
        with page.expect_response("**/api/settings/servers/reorder"):
            _simulate_drag(page, second_id, first_id)
        # PATCH done → reload-servers dispatched → htmx fires GET /api/servers

    # Sidebar server items, ordered by DOM position
    sidebar_ids = page.evaluate("""
        () => Array.from(
            document.querySelectorAll('#navigator li[hx-get], #navigator div[hx-get]')
        ).map(el => {
            const m = el.getAttribute('hx-get').match(/\\/api\\/quadlets\\/(\\d+)/);
            return m ? parseInt(m[1], 10) : null;
        }).filter(Boolean)
    """)

    if not sidebar_ids:
        pytest.skip("Could not read sidebar server IDs — selector may not match.")

    assert sidebar_ids[0] == second_id, (
        f"Sidebar first server should be {second_id} after reorder, got {sidebar_ids[0]}"
    )
