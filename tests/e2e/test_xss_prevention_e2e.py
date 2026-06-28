"""
E2E tests to verify DOM-based XSS prevention in main.js.
"""
import pytest

try:
    from playwright.sync_api import Page
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


def _goto_dashboard(page: Page):
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")


@pytest.mark.e2e
def test_confirm_delete_file_xss_prevention(page: Page):
    """confirmDeleteFile must not execute embedded scripts in filename."""
    _goto_dashboard(page)
    
    page.evaluate("""() => {
        window.xssConfirmed = false;
        // Call confirmDeleteFile with a payload that exploits onclick attribute injection
        window.confirmDeleteFile(1, '/some/path/a" onclick="window.xssConfirmed=true" name="', 'user');
    }""")
    
    # Click the delete button in the modal to trigger the onclick
    page.click("#delete-confirm-modal .btn-danger")
    
    # Wait a tiny bit for any potential rendering and script execution
    page.wait_for_timeout(500)
    
    xss_confirmed = page.evaluate("window.xssConfirmed")
    assert not xss_confirmed, "XSS vulnerability detected in confirmDeleteFile: script executed!"


@pytest.mark.e2e
def test_execute_delete_file_xss_prevention(page: Page):
    """executeDeleteFile must not execute embedded scripts returned from API."""
    _goto_dashboard(page)
    
    # Mock the API response to return a malicious HTML payload
    page.route("**/api/files*", lambda route: route.fulfill(
        status=200,
        content_type="text/html",
        body="<div class='toast-msg toast-green toast-enter'>Deleted <img src=x onerror='window.xssConfirmed=true'>!</div>"
    ))
    
    page.evaluate("""() => {
        window.xssConfirmed = false;
        // Call executeDeleteFile
        window.executeDeleteFile(1, "/some/path", "user");
    }""")
    
    page.wait_for_timeout(500)
    
    xss_confirmed = page.evaluate("window.xssConfirmed")
    assert not xss_confirmed, "XSS vulnerability detected in executeDeleteFile toast insertion: script executed!"


@pytest.mark.e2e
def test_render_container_stats_table_xss_prevention(page: Page):
    """renderContainerStatsTable must not execute embedded scripts in container names."""
    _goto_dashboard(page)
    
    page.evaluate("""() => {
        window.xssConfirmed = false;
        const data = {
            server_id: 1,
            server_name: "test-server",
            containers: [{
                name: "<img src=x onerror='window.xssConfirmed=true'>",
                cpu: "1.00%",
                mem: "2.00%",
                net_io: "0B / 0B",
                pids: "1"
            }]
        };
        window.renderContainerStatsTable("stats-table", data);
    }""")
    
    page.wait_for_timeout(500)
    
    xss_confirmed = page.evaluate("window.xssConfirmed")
    assert not xss_confirmed, "XSS vulnerability detected in renderContainerStatsTable: script executed!"


@pytest.mark.e2e
def test_update_inspector_activity_log_xss_prevention(page: Page):
    """updateInspectorActivityLog must not execute embedded scripts in activity events."""
    _goto_dashboard(page)
    
    # Mock the activity log endpoint to return malicious event data
    page.route("**/api/activity/*", lambda route: route.fulfill(
        status=200,
        content_type="application/json",
        body='{"events": [{"event_type": "<img src=x onerror=\'window.xssConfirmed=true\'>", "occurred_at": 1719547000, "triggered_by": "user"}]}'
    ))
    
    page.evaluate("""() => {
        window.xssConfirmed = false;
        // Open activity log / call the updater
        window.updateInspectorActivityLog(1, "my-container");
    }""")
    
    page.wait_for_timeout(500)
    
    xss_confirmed = page.evaluate("window.xssConfirmed")
    assert not xss_confirmed, "XSS vulnerability detected in updateInspectorActivityLog: script executed!"
