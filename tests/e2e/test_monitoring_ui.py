import json
import pytest
from playwright.sync_api import Page, expect, Error as PlaywrightError
import contextlib

# To run this, the backend must be running on localhost:8000
# DEV_AUTO_LOGIN=1 venv/bin/uvicorn main:app --port 8000

# Shared read-only fixtures. Tests pass these straight to page.evaluate or
# json.dumps and must never mutate them.
WEB_CONTAINER = {"name": "web", "cpu": "5.0%", "mem": "10.0%", "net_io": "1kB / 1kB", "health": "healthy"}
DB_CONTAINER = {"name": "db", "cpu": "2.0%", "mem": "20.0%", "net_io": "1kB / 1kB", "health": "healthy"}
CACHE_CONTAINER = {"name": "cache", "cpu": "1.0%", "mem": "4.0%", "net_io": "1kB / 1kB", "health": "healthy"}

TWO_CONTAINER_HISTORY = [
    {"container_name": "web", "history": [{"ts": 1000, "cpu": 5.0, "mem": 10.0}]},
    {"container_name": "db", "history": [{"ts": 1000, "cpu": 2.0, "mem": 20.0}]},
]


def open_monitor_pane(page: Page, history=None):
    """Load the app and switch to the Monitor tab, skipping if no backend.

    When `history` is given, the chart history endpoint is stubbed with that
    body before the Monitor tab is opened, so no real fetch can slip through.
    """
    try:
        page.goto("http://localhost:8000/")
    except PlaywrightError:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")

    page.locator("#navigator").get_by_text("Loading servers...").wait_for(state="hidden")

    if history is not None:
        page.route(
            "**/api/health/history/*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(history),
            ),
        )

    page.click("button.nav-item:has-text('Monitor')")
    expect(page.locator("#monitoring-pane")).to_be_visible()


def inject_stats(page: Page, server_id, server_name, containers, units=None):
    """Push a stats frame straight into the client, bypassing the SSE stream.

    When `units` is not None, a `units` key is included in the injected
    payload; when it is None, the key is omitted entirely (an absent `units`
    key is a distinct, meaningful state and must not become `[]`).
    """
    page.evaluate(
        """([serverId, serverName, containers, units]) => {
            const payload = {
                server_id: serverId,
                server_name: serverName,
                containers: containers,
            };
            if (units !== null) {
                payload.units = units;
            }
            window.handleStatsUpdate({
                data: JSON.stringify(payload)
            });
        }""",
        [server_id, server_name, containers, units],
    )


def select_injected_server(page: Page, server_id, option_count):
    """Select an injected server once the dropdown has `option_count` options.

    Injecting stats directly causes main.js to auto-adopt the first injected
    server as "active" before the dropdown is ever touched; clearing that makes
    the select_option() below exercise the normal server-selection code path.
    """
    page.wait_for_function(
        "document.getElementById('monitoring-server-select').options.length >= "
        f"{option_count}"
    )
    page.evaluate("window.activeServerId = null")
    page.locator("#monitoring-server-select").select_option(str(server_id))
    page.evaluate(
        """([id]) => {
            const sel = document.getElementById('monitoring-server-select');
            if (sel) sel.dispatchEvent(new Event('change', { bubbles: true }));
            if (window.selectMonitoringServer) {
                window.selectMonitoringServer(id);
            }
        }""",
        [server_id],
    )
    expect(page.locator("#monitoring-content")).to_be_visible()



def wait_for_chart_series(page: Page, count):
    page.wait_for_function(
        "Chart.getChart('cpu-history-chart') && "
        "Chart.getChart('cpu-history-chart').data.datasets.length === "
        f"{count}"
    )


def assert_chart_series(page: Page, expected, context):
    """Assert both history charts carry exactly `expected` dataset labels."""
    for canvas_id, chart_name in (("cpu-history-chart", "CPU"), ("mem-history-chart", "Memory")):
        labels = page.evaluate(
            f"Chart.getChart('{canvas_id}').data.datasets.map(d => d.label)"
        )
        assert labels == expected, f"{chart_name} chart {context}: {labels}"


def assert_only_row(page: Page, name):
    """Assert the stats table shows exactly one row, for container `name`."""
    rows = page.locator("#monitoring-stats-table table tbody tr")
    expect(rows).to_have_count(1)
    expect(rows.first.locator("td").first).to_have_text(name)


@pytest.mark.e2e
def test_glance_bar_hidden_when_no_server_selected(page: Page):
    """Stat bar must stay hidden when no server is selected in the Monitor tab.

    Regression guard for issue #96: stats arriving via WebSocket for any
    server were unconditionally making the stat bar visible, even while the
    empty-state placeholder was showing — causing it to drift to the bottom.
    """
    # No server is selected in the dropdown yet.
    open_monitor_pane(page)

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
    open_monitor_pane(page)

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
    open_monitor_pane(page)

    # Ensure a real server from the dropdown is selected.
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
    open_monitor_pane(page, history=TWO_CONTAINER_HISTORY)

    # Inject two synthetic servers' stats so the test is deterministic
    # regardless of what is actually being monitored on this machine.
    inject_stats(page, 1, "Server A", [WEB_CONTAINER, DB_CONTAINER])
    inject_stats(page, 2, "Server B", [WEB_CONTAINER, DB_CONTAINER])

    # Both injected servers, plus the placeholder option.
    select_injected_server(page, 1, option_count=3)
    select = page.locator("#monitoring-server-select")

    # Wait for the (mocked) chart history fetch triggered by server selection
    # to populate both datasets.
    wait_for_chart_series(page, 2)

    # Apply a filter that should isolate the "web" container only.
    filter_input = page.locator("#monitor-container-filter")
    filter_input.fill("web")

    # Re-trigger a chart data load (as a range-button click would in normal
    # use) so any filtering logic has a chance to run.
    page.click(".health-range-btn.active")
    page.wait_for_timeout(500)

    # The stats table must only show the filtered container.
    assert_only_row(page, "web")

    # The CPU and Memory history charts must also only show the filtered
    # container as a dataset.
    assert_chart_series(page, ["web"], "showed unfiltered containers")

    # Switch to the other server — the filter value must be preserved, not
    # cleared, and continue to be applied.
    select.select_option("2")
    expect(page.locator("#monitoring-content")).to_be_visible()

    expect(filter_input).to_have_value("web")

    page.wait_for_timeout(500)
    assert_only_row(page, "web")


@pytest.mark.e2e
def test_monitor_filter_drops_chart_series_without_a_chart_rebuild(page: Page):
    """Typing in the filter box must remove already-drawn chart series.

    The filter input only calls applyContainerFilter() -> updateMonitoringView(),
    which appends to the existing charts; it never refetches history. So a
    series drawn before the filter was typed has to be pruned on that append
    path, otherwise it stays on the canvas (and drifts out of step with the
    shared labels, which keep being trimmed under it).

    Regression guard for issue #259 — distinct from the test above, which
    clicks a range button and therefore exercises the full-rebuild path.
    """
    open_monitor_pane(page, history=TWO_CONTAINER_HISTORY)

    inject_stats(page, 1, "Server A", [WEB_CONTAINER, DB_CONTAINER])
    select_injected_server(page, 1, option_count=2)

    # Both series are drawn before any filter is applied.
    wait_for_chart_series(page, 2)

    # Type in the filter box. This fires oninput -> applyContainerFilter only;
    # no range button is clicked, so no history refetch/rebuild happens.
    page.locator("#monitor-container-filter").fill("web")

    # Drive one more stats tick through the append path.
    inject_stats(page, 1, "Server A", [WEB_CONTAINER, DB_CONTAINER])
    page.wait_for_timeout(300)

    assert_chart_series(page, ["web"], "kept a filtered-out series")


@pytest.mark.e2e
def test_monitor_filter_narrows_glance_bar_and_shows_match_count(page: Page):
    """The glance bar must count only containers matching the filter, and the
    "N of M shown" indicator must report the match count.

    Regression guard for issue #259: the glance bar previously received
    unfiltered data, so its totals described the whole server while the table
    and charts showed a subset.
    """
    open_monitor_pane(page, history=[])

    units = [
        {"unit": "web.service", "scope": "user", "load_state": "loaded", "active_state": "active", "sub_state": "running", "n_restarts": 0},
        {"unit": "db.service", "scope": "user", "load_state": "loaded", "active_state": "active", "sub_state": "running", "n_restarts": 0},
        {"unit": "cache.service", "scope": "user", "load_state": "loaded", "active_state": "active", "sub_state": "running", "n_restarts": 0},
    ]
    inject_stats(page, 1, "Server A", [WEB_CONTAINER, DB_CONTAINER, CACHE_CONTAINER], units=units)
    select_injected_server(page, 1, option_count=2)

    count_el = page.locator("#monitor-filter-count")

    # With no filter the indicator is noise, so it stays hidden.
    expect(count_el).to_be_hidden()
    expect(page.locator("#mstat-running")).to_have_text("3")
    expect(page.locator("#mstat-total")).to_have_text("3")

    # Filtering to a single container must narrow the glance bar too. The two
    # excluded containers are still running, so they must not be counted as
    # stopped.
    page.locator("#monitor-container-filter").fill("web")

    expect(count_el).to_be_visible()
    expect(count_el).to_have_text("1 of 3 shown")
    expect(page.locator("#mstat-running")).to_have_text("1")
    expect(page.locator("#mstat-total")).to_have_text("1")
    expect(page.locator("#mstat-stopped")).to_have_text("0")

    # A filter matching nothing zeroes the counts rather than going negative.
    page.locator("#monitor-container-filter").fill("nomatch")

    expect(count_el).to_have_text("0 of 3 shown")
    expect(page.locator("#mstat-running")).to_have_text("0")
    expect(page.locator("#mstat-stopped")).to_have_text("0")

    # Clearing the filter restores the whole-server view and hides the count.
    page.locator("#monitor-container-filter").fill("")

    expect(count_el).to_be_hidden()
    expect(page.locator("#mstat-running")).to_have_text("3")


@pytest.mark.e2e
def test_glance_bar_counts_come_from_unit_state(page: Page):
    """TOTAL, RUNNING and STOPPED must be derived from the `units` array in
    the stats payload, not from the containers list.

    Regression guard for issue #258: the old Set-based derivation
    (`allSeenContainersBySid`, seeded only from running containers) would
    report 1 / 1 / 0 from the stray container alone, ignoring the actual
    Quadlet unit state entirely.
    """
    open_monitor_pane(page, history=[])

    stray_container = {"name": "stray", "cpu": "1.0%", "mem": "1.0%", "net_io": "1kB / 1kB", "health": "healthy"}
    units = [
        {"unit": "web.service", "scope": "user", "load_state": "loaded", "active_state": "active", "sub_state": "running", "n_restarts": 0},
        {"unit": "db.service", "scope": "user", "load_state": "loaded", "active_state": "active", "sub_state": "running", "n_restarts": 0},
        {"unit": "cache.service", "scope": "user", "load_state": "loaded", "active_state": "inactive", "sub_state": "dead", "n_restarts": 0},
    ]

    inject_stats(page, 999, "Server Synthetic", [stray_container], units=units)
    select_injected_server(page, 999, option_count=2)

    expect(page.locator("#mstat-total")).to_have_text("3")
    expect(page.locator("#mstat-running")).to_have_text("2")
    expect(page.locator("#mstat-stopped")).to_have_text("1")
