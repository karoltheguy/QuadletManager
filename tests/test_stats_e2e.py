import pytest
import time
from playwright.sync_api import Page, expect

# To run this, the backend must be running on localhost:8000
# DEV_AUTO_LOGIN=1 venv/bin/uvicorn main:app --port 8000

def test_stats_update_received(page: Page):
    """Test that the stats table updates when receiving SSE events"""
    page.goto("http://localhost:8000/")
    
    # Wait for the servers list to load (Loading servers... disappear)
    page.locator("text='Loading servers...'").wait_for(state="hidden")
    
    # Wait for the stats table to contain either a table or a 'No containers' or 'Stats unavailable' message
    # This proves that updateStats or stats_error handler was called from the SSE listener
    try:
        # We wait up to 12 seconds because the stats loop runs every 5 seconds
        page.wait_for_selector("#stats-table table, #stats-table .italic, #stats-table .text-red-400", timeout=12000)
    except Exception:
        content = page.locator("#stats-table").inner_text()
        pytest.fail(f"Stats table did not update in time. Current content: {content}")

    # Verify that the chart canvas is present
    expect(page.locator("#stats-chart")).to_be_visible()

def test_log_streaming_ui(page: Page):
    """Test that clicking Tail Logs changes button state and shows message"""
    page.goto("http://localhost:8000/")
    
    # Wait for servers and files to load
    page.locator("text='Loading servers...'").wait_for(state="hidden")
    
    # Wait for any .container file to appear in the sidebar
    # We use a partial text match because the emoji might render differently
    file_btn = page.get_by_role("button", name=".container").first
    file_btn.click()
    
    # Wait for Tail Logs button to appear in the inspector
    page.wait_for_selector("#toggle-logs-btn", timeout=10000)
    
    btn = page.locator("#toggle-logs-btn")
    expect(btn).to_have_text("Tail Logs")
    
    # Click Tail Logs
    btn.click()
    
    # Button text should change
    expect(btn).to_have_text("Stop Logs")
    
    # Status div should show connecting message
    status_div = page.locator("#systemd-status")
    expect(status_div).to_contain_text("Connecting to log stream...")
    
    # Click Stop Logs
    btn.click()
    expect(btn).to_have_text("Tail Logs")
    expect(status_div).to_contain_text("Stopped log stream")
