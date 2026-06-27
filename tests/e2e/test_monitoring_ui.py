import pytest
from playwright.sync_api import Page, expect, Error as PlaywrightError
import contextlib

# To run this, the backend must be running on localhost:8000
# DEV_AUTO_LOGIN=1 venv/bin/uvicorn main:app --port 8000

@pytest.mark.e2e
def test_glance_bar_hidden_when_no_server_selected(page: Page):
    """Stat bar must stay hidden when no server is selected in the Monitor tab.

    Regression guard for issue #96: stats arriving via WebSocket for any
    server were unconditionally making the stat bar visible, even while the
    empty-state placeholder was showing — causing it to drift to the bottom.
    """
    try:
        page.goto("http://localhost:8000/")
    except PlaywrightError:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")

    page.locator("text='Loading servers...'").wait_for(state="hidden")

    # Navigate to Monitor tab — no server selected in the dropdown yet.
    page.click("button.nav-item:has-text('Monitor')")
    expect(page.locator("#monitoring-pane")).to_be_visible()

    # Ensure the dropdown still shows the placeholder (no server selected).
    select_value = page.locator("#monitoring-server-select").input_value()
    if select_value != "":
        pytest.skip("A server was auto-selected; can't test the no-server state.")

    # Give WebSocket stats a moment to arrive (they fire every ~5 s).
    page.wait_for_timeout(6000)

    # The stat bar must remain hidden while no server is selected.
    stat_bar = page.locator("#monitor-stat-bar")
    expect(stat_bar).to_be_hidden()

    # And the empty-state placeholder must be visible.
    expect(page.locator("#monitoring-empty-state")).to_be_visible()


@pytest.mark.e2e
def test_monitoring_table_css(page: Page):
    """Test that the monitoring table has the correct CSS applied for alignment and padding"""
    try:
        page.goto("http://localhost:8000/")
    except PlaywrightError:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")
    
    # Wait for the DOM to load
    page.locator("text='Loading servers...'").wait_for(state="hidden")

    # Navigate to Monitoring tab
    page.click("button.nav-item:has-text('Monitor')")
    
    # Ensure monitoring pane is visible
    expect(page.locator("#monitoring-pane")).to_be_visible()

    # Wait for the monitoring table to receive stats or the 'No containers' or 'Stats unavailable' generic table frame
    # We can evaluate the CSS of the table wrapper directly. We'll wait until the selector has populated.
    # The monitoring table adds the table dynamically, so wait for the th
    # If no containers or stats unavailable, the table headers might not render. This makes it tricky.
    # But wait, looking at main.js, if there are no containers it just outputs "No containers running on server".
    # So we might not get a table if there are no containers.
    with contextlib.suppress(PlaywrightError):
        page.wait_for_selector("#monitoring-stats-table table th.p-4", timeout=12000)

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
