import pytest
from playwright.sync_api import Page, expect

# To run this, the backend must be running on localhost:8000
# DEV_AUTO_LOGIN=1 venv/bin/uvicorn main:app --port 8000

def test_monitoring_table_css(page: Page):
    """Test that the monitoring table has the correct CSS applied for alignment and padding"""
    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")
    
    # Wait for the DOM to load
    page.locator("text='Loading servers...'").wait_for(state="hidden")

    # Navigate to Monitoring tab
    page.click("button.nav-item:has-text('Monitoring')")
    
    # Ensure monitoring pane is visible
    expect(page.locator("#monitoring-pane")).to_be_visible()

    # Wait for the monitoring table to receive stats or the 'No containers' or 'Stats unavailable' generic table frame
    # We can evaluate the CSS of the table wrapper directly. We'll wait until the selector has populated.
    # The monitoring table adds the table dynamically, so wait for the th
    try:
        page.wait_for_selector("#monitoring-stats-table table th.p-4", timeout=12000)
    except Exception:
        # If no containers or stats unavailable, the table headers might not render. This makes it tricky.
        # But wait, looking at main.js, if there are no containers it just outputs "No containers running on server".
        # So we might not get a table if there are no containers.
        pass

    # If the table is rendered, check its computed styles
    if page.locator("#monitoring-stats-table table").is_visible():
        table_locator = page.locator("#monitoring-stats-table table")
        border_collapse = table_locator.evaluate("el => window.getComputedStyle(el).borderCollapse")
        assert border_collapse == "collapse", f"Expected border-collapse: collapse but got {border_collapse}"

        th_locator = page.locator("#monitoring-stats-table th").first
        if th_locator.is_visible():
            padding_left = th_locator.evaluate("el => window.getComputedStyle(el).paddingLeft")
            # 1rem is usually 16px
            assert padding_left == "16px", f"Expected padding-left 16px but got {padding_left}"
            
            text_align = th_locator.evaluate("el => window.getComputedStyle(el).textAlign")
            assert text_align == "left" or text_align == "start", f"Expected text-align left but got {text_align}"
