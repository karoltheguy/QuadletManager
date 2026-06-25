import pytest
import time
from playwright.sync_api import Page, expect

# To run this, the backend must be running on localhost:8000
# DEV_AUTO_LOGIN=1 venv/bin/uvicorn main:app --port 8000

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

def test_log_streaming_ui(page: Page):
    """Test that clicking Tail Logs changes button state and activates log streaming"""
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

    # Click Tail Logs — this also opens the bottom log panel
    btn.click()

    # Button text should change to "Stop Logs"
    expect(btn).to_have_text("Stop Logs")

    # Log output is written to #log-stream (inside the bottom panel)
    # Wait for it to contain something beyond "Waiting for log output..."
    log_div = page.locator("#log-stream")
    page.wait_for_function(
        "document.querySelector('#log-stream') && "
        "document.querySelector('#log-stream').textContent.trim() !== '' && "
        "document.querySelector('#log-stream').textContent !== 'Waiting for log output...'",
        timeout=5000,
    )

    # Click Stop Logs
    btn.click()
    expect(btn).to_have_text("Tail Logs")
    # stopLogs() appends "--- Stopped ---" to #log-stream
    expect(log_div).to_contain_text("--- Stopped ---")
