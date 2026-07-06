import pytest
from playwright.sync_api import Page, expect

# To run this, the backend must be running on localhost:8000
# DEV_AUTO_LOGIN=1 venv/bin/uvicorn main:app --port 8000

@pytest.mark.e2e
def test_stats_update_received(page: Page):
    """Test that the stats table updates when receiving SSE events"""
    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")

    # Wait for the servers list to load (Loading servers... disappear)
    page.locator("text='Loading servers...'").wait_for(state="hidden")

    # Stats table is in the Monitor tab
    page.click("button.nav-item:has-text('Monitor')")

    # Wait for the server dropdown to be populated (SSE stats arrive within ~5 seconds)
    try:
        page.wait_for_function(
            "document.querySelector('#monitoring-server-select option:not([value=\"\"])') !== null",
            timeout=12000,
        )
    except Exception:
        pytest.skip("No servers available in monitoring dropdown — skipping stats test.")

    # Select the first available server so #monitoring-content becomes visible
    page.select_option("#monitoring-server-select", index=1)

    # Wait for the stats table to contain either a table or a status message
    try:
        page.wait_for_selector(
            "#monitoring-stats-table table, #monitoring-stats-table .italic, #monitoring-stats-table .text-danger",
            timeout=12000,
        )
    except Exception:
        content = page.locator("#monitoring-stats-table").inner_text()
        pytest.fail(f"Stats table did not update in time. Current content: {content}")

    # Verify that the CPU history chart canvas is present
    expect(page.locator("#cpu-history-chart")).to_be_visible()

@pytest.mark.e2e
def test_log_streaming_ui(page: Page):
    """Test that clicking Tail Logs opens a log chip and streams content into its pane.

    Issue #123: the header button is create-or-switch only (mirrors the terminal
    Connect button) — it no longer toggles to "Stop Logs". Stopping a tail is done
    by closing its chip in the shared sessions strip.
    """
    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")

    # Wait for servers and files to load
    page.locator("text='Loading servers...'").wait_for(state="hidden")

    # Navigator (sidebar with quadlet files) is only visible on the Containers tab
    page.click("button.nav-item:has-text('Containers')")

    # Wait for any .container file to appear in the sidebar
    try:
        file_btn = page.get_by_role("button", name=".container").first
        file_btn.wait_for(timeout=5000)
        file_btn.click()
    except Exception:
        pytest.skip("No container files available in sidebar — skipping log streaming E2E test.")

    # Wait for Tail Logs button to appear in the inspector
    page.wait_for_selector("#toggle-logs-btn", timeout=10000)

    btn = page.locator("#toggle-logs-btn")
    expect(btn).to_have_text("Tail Logs")

    # Click Tail Logs — this also opens the bottom log panel and creates a chip
    btn.click()

    expect(page.locator(".log-conn-tab")).to_have_count(1)
    expect(btn).to_have_text("Tail Logs")

    # Log output streams into the active tab's .log-stream pane.
    # Wait for it to contain something beyond "Connecting to log stream..."
    page.wait_for_function(
        "document.querySelector('.log-tab-pane:not(.hidden) .log-stream') && "
        "document.querySelector('.log-tab-pane:not(.hidden) .log-stream').textContent.trim() !== '' && "
        "document.querySelector('.log-tab-pane:not(.hidden) .log-stream').textContent !== 'Connecting to log stream...'",
        timeout=5000,
    )

    # Close the chip — this stops the underlying WebSocket.
    page.locator(".log-conn-tab-close").click()
    expect(page.locator(".log-conn-tab")).to_have_count(0, timeout=5000)
    expect(page.locator("#log-empty-hint")).to_be_visible()
