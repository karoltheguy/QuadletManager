import json
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

    page.locator("#navigator").get_by_text("Loading servers...").wait_for(state="hidden")

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
    page.locator("#navigator").get_by_text("Loading servers...").wait_for(state="hidden")

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


@pytest.mark.e2e
def test_monitor_charts_show_error_on_history_fetch_failure(page: Page):
    """When /api/health/history/{serverId} fails, the Monitor pane must show
    a visible error message — not just fail silently or log to console.

    Regression guard for issue #260.
    """
    try:
        page.goto("http://localhost:8000/")
    except PlaywrightError:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")

    page.locator("#navigator").get_by_text("Loading servers...").wait_for(state="hidden")

    # Navigate to Monitor tab and ensure a server is selected.
    page.click("button.nav-item:has-text('Monitor')")
    expect(page.locator("#monitoring-pane")).to_be_visible()

    select = page.locator("#monitoring-server-select")
    select_value = select.input_value()
    if select_value == "":
        # Server options populate from WebSocket stats, which arrive on an
        # interval; give them a moment to show up before giving up.
        with contextlib.suppress(PlaywrightError):
            page.wait_for_function(
                "document.getElementById('monitoring-server-select').options.length > 1",
                timeout=8000,
            )
        options = select.locator("option").all()
        candidate_values = [
            opt.get_attribute("value") for opt in options
            if opt.get_attribute("value")
        ]
        if not candidate_values:
            pytest.skip("No servers available to select for this test.")
        select.select_option(candidate_values[0])

    expect(page.locator("#monitoring-content")).to_be_visible()

    # Mock the chart history endpoint to fail with a 500 error.
    page.route(
        "**/api/health/history/*",
        lambda route: route.fulfill(
            status=500,
            content_type="application/json",
            body='{"detail": "Internal Server Error"}',
        ),
    )

    # Trigger a chart history fetch via one of the range buttons.
    page.click(".health-range-btn.active")

    # A visible error message must appear on the Monitor pane.
    error_el = page.locator("#monitor-charts-error")
    expect(error_el).to_be_visible()

    # The empty-state placeholder must not be shown instead of the error.
    expect(page.locator("#monitor-charts-empty")).to_be_hidden()


@pytest.mark.e2e
def test_monitor_container_filter_applies_to_charts_and_persists_across_servers(page: Page):
    """The container filter must apply to both the stats table AND the
    CPU/Memory history charts, and its value must persist (not reset) when
    switching servers in the dropdown.

    Regression guard for issue #259.
    """
    try:
        page.goto("http://localhost:8000/")
    except PlaywrightError:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")

    page.locator("text='Loading servers...'").wait_for(state="hidden")

    # Mock the chart history endpoint so both containers are always returned
    # by the backend, regardless of any client-side filter — this isolates
    # the client-side filtering behavior under test.
    def fulfill_history(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([
                {"container_name": "web", "history": [{"ts": 1000, "cpu": 5.0, "mem": 10.0}]},
                {"container_name": "db", "history": [{"ts": 1000, "cpu": 2.0, "mem": 20.0}]},
            ]),
        )

    page.route("**/api/health/history/*", fulfill_history)

    # Navigate to Monitor tab.
    page.click("button.nav-item:has-text('Monitor')")
    expect(page.locator("#monitoring-pane")).to_be_visible()

    # Inject two synthetic servers' stats directly (bypassing the real SSE
    # stream) so the test is deterministic regardless of what is actually
    # being monitored on this machine.
    web_container = {"name": "web", "cpu": "5.0%", "mem": "10.0%", "net_io": "1kB / 1kB", "health": "healthy"}
    db_container = {"name": "db", "cpu": "2.0%", "mem": "20.0%", "net_io": "1kB / 1kB", "health": "healthy"}

    def inject_stats(server_id, server_name, containers):
        page.evaluate(
            """([serverId, serverName, containers]) => {
                window.handleStatsUpdate({
                    data: JSON.stringify({
                        server_id: serverId,
                        server_name: serverName,
                        containers: containers,
                    })
                });
            }""",
            [server_id, server_name, containers],
        )

    inject_stats(1, "Server A", [web_container, db_container])
    inject_stats(2, "Server B", [web_container, db_container])

    # Wait for the dropdown to populate with both injected servers (plus the
    # placeholder option).
    page.wait_for_function(
        "document.getElementById('monitoring-server-select').options.length >= 3"
    )

    # Injecting stats directly (rather than via a real SSE stream) causes
    # main.js to auto-adopt the first injected server as "active" before we
    # ever touch the dropdown; clear that so the upcoming select_option()
    # exercises the normal server-selection code path.
    page.evaluate("window.activeServerId = null")

    select = page.locator("#monitoring-server-select")
    select.select_option("1")
    expect(page.locator("#monitoring-content")).to_be_visible()

    # Wait for the (mocked) chart history fetch triggered by server selection
    # to populate both datasets.
    page.wait_for_function(
        "Chart.getChart('cpu-history-chart') && "
        "Chart.getChart('cpu-history-chart').data.datasets.length === 2"
    )

    # Apply a filter that should isolate the "web" container only.
    filter_input = page.locator("#monitor-container-filter")
    filter_input.fill("web")

    # Re-trigger a chart data load (as a range-button click would in normal
    # use) so any filtering logic has a chance to run.
    page.click(".health-range-btn.active")
    page.wait_for_timeout(500)

    # The stats table must only show the filtered container.
    table_rows = page.locator("#monitoring-stats-table table tbody tr")
    expect(table_rows).to_have_count(1)
    expect(table_rows.first.locator("td").first).to_have_text("web")

    # The CPU and Memory history charts must also only show the filtered
    # container as a dataset — this is the part that currently fails.
    cpu_labels = page.evaluate(
        "Chart.getChart('cpu-history-chart').data.datasets.map(d => d.label)"
    )
    mem_labels = page.evaluate(
        "Chart.getChart('mem-history-chart').data.datasets.map(d => d.label)"
    )
    assert cpu_labels == ["web"], (
        f"Expected only the filtered container in the CPU chart, got {cpu_labels}"
    )
    assert mem_labels == ["web"], (
        f"Expected only the filtered container in the Memory chart, got {mem_labels}"
    )

    # Switch to the other server — the filter value must be preserved, not
    # cleared, and continue to be applied.
    select.select_option("2")
    expect(page.locator("#monitoring-content")).to_be_visible()

    expect(filter_input).to_have_value("web")

    page.wait_for_timeout(500)
    table_rows_after_switch = page.locator("#monitoring-stats-table table tbody tr")
    expect(table_rows_after_switch).to_have_count(1)
    expect(table_rows_after_switch.first.locator("td").first).to_have_text("web")
