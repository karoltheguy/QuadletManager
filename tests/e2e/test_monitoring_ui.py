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

TWO_CONTAINER_HISTORY_REVERSED = [
    {"container_name": "db", "history": [{"ts": 1000, "cpu": 2.0, "mem": 20.0}]},
    {"container_name": "web", "history": [{"ts": 1000, "cpu": 5.0, "mem": 10.0}]},
]

THREE_CONTAINER_HISTORY = [
    {"container_name": "web", "history": [{"ts": 1000, "cpu": 5.0, "mem": 10.0}]},
    {"container_name": "db", "history": [{"ts": 1000, "cpu": 2.0, "mem": 20.0}]},
    {"container_name": "cache", "history": [{"ts": 1000, "cpu": 1.0, "mem": 4.0}]},
]


def servers_options_html(servers):
    """Render the `<option>` list that /api/servers/options returns."""
    options = '<option value="">Select a server...</option>'
    for server_id, name in servers:
        options += f'<option value="{server_id}">{name}</option>'
    return options


def open_monitor_pane(page: Page, history=None, servers=None):
    """Load the app and switch to the Monitor tab, skipping if no backend.

    When `history` is given, the chart history endpoint is stubbed with that
    body before the Monitor tab is opened, so no real fetch can slip through.

    When `servers` is given as a list of (id, name) pairs, /api/servers/options
    is stubbed with them. The dropdown is populated from the database, not from
    telemetry (issue #365), so a test using synthetic server ids has to supply
    them here or they will never appear as options. The stub is installed before
    the navigation because the select fetches on `hx-trigger="load"`.
    """
    if servers is not None:
        body = servers_options_html(servers)
        page.route(
            "**/api/servers/options",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body=body,
            ),
        )

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
    """Select a server once the dropdown has `option_count` options.

    The dropdown selection drives the Monitor pane on its own, via
    `window._monitoringServerId`. The option must already exist, which means
    the test supplied `servers=` to `open_monitor_pane`.
    """
    page.wait_for_function(
        "document.getElementById('monitoring-server-select').options.length >= "
        f"{option_count}"
    )
    page.locator("#monitoring-server-select").select_option(str(server_id))
    page.evaluate(
        """() => {
            const sel = document.getElementById('monitoring-server-select');
            if (sel) sel.dispatchEvent(new Event('change', { bubbles: true }));
        }"""
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
    """Assert the stats table shows exactly one row, for container `name`.

    The first `<td>` is the leading chart-swatch cell (issue #256), so the
    container name lives in the second `<td>` instead.
    """
    rows = page.locator("#monitoring-stats-table table tbody tr")
    expect(rows).to_have_count(1)
    expect(rows.first.locator("td").nth(1)).to_have_text(name)


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
        page.evaluate(
            """() => {
                const sel = document.getElementById('monitoring-server-select');
                if (sel) sel.dispatchEvent(new Event('change', { bubbles: true }));
            }"""
        )

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
    open_monitor_pane(
        page,
        history=TWO_CONTAINER_HISTORY,
        servers=[(201, "Server A"), (202, "Server B")],
    )

    # Inject two synthetic servers' stats so the test is deterministic
    # regardless of what is actually being monitored on this machine.
    inject_stats(page, 201, "Server A", [WEB_CONTAINER, DB_CONTAINER])
    inject_stats(page, 202, "Server B", [WEB_CONTAINER, DB_CONTAINER])

    # Both injected servers, plus the placeholder option.
    select_injected_server(page, 201, option_count=3)
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
    select.select_option("202")
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
    open_monitor_pane(
        page,
        history=TWO_CONTAINER_HISTORY,
        servers=[(201, "Server A")],
    )

    inject_stats(page, 201, "Server A", [WEB_CONTAINER, DB_CONTAINER])
    select_injected_server(page, 201, option_count=2)

    # Both series are drawn before any filter is applied.
    wait_for_chart_series(page, 2)

    # Type in the filter box. This fires oninput -> applyContainerFilter only;
    # no range button is clicked, so no history refetch/rebuild happens.
    page.locator("#monitor-container-filter").fill("web")

    # Drive one more stats tick through the append path.
    inject_stats(page, 201, "Server A", [WEB_CONTAINER, DB_CONTAINER])
    page.wait_for_timeout(300)

    assert_chart_series(page, ["web"], "kept a filtered-out series")


@pytest.mark.e2e
def test_chart_colors_are_stable_across_history_reordering(page: Page):
    """A container's chart line color must be derived from its name, not from
    its position in the array that built the dataset.

    `loadMonitorCharts` assigns colors with `HISTORY_COLORS[i % HISTORY_COLORS.length]`
    where `i` is the index into the filtered history array, so reordering the
    history payload reassigns colors instead of keeping them tied to the
    container name.
    """
    open_monitor_pane(
        page,
        history=TWO_CONTAINER_HISTORY,
        servers=[(101, "srv-a")],
    )

    inject_stats(page, 101, "srv-a", [WEB_CONTAINER, DB_CONTAINER])
    select_injected_server(page, 101, 2)
    wait_for_chart_series(page, 2)

    colors_before = page.evaluate(
        "Object.fromEntries(Chart.getChart('cpu-history-chart').data.datasets"
        ".map(d => [d.label, d.borderColor]))"
    )

    # Re-stub the history endpoint with the containers in the opposite order.
    page.route(
        "**/api/health/history/*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(TWO_CONTAINER_HISTORY_REVERSED),
        ),
    )

    # Trigger a range reload so the reversed payload is actually fetched.
    page.click(".health-history-controls .health-range-btn:has-text('6h')")

    wait_for_chart_series(page, 2)
    page.wait_for_function(
        "Chart.getChart('cpu-history-chart').data.datasets.map(d => d.label)"
        "[0] === 'db'"
    )

    colors_after = page.evaluate(
        "Object.fromEntries(Chart.getChart('cpu-history-chart').data.datasets"
        ".map(d => [d.label, d.borderColor]))"
    )

    assert colors_after["web"] == colors_before["web"], (
        f"web color changed from {colors_before['web']} to {colors_after['web']}"
    )
    assert colors_after["db"] == colors_before["db"], (
        f"db color changed from {colors_before['db']} to {colors_after['db']}"
    )


def _chart_visibility_map(page: Page, canvas_id):
    """Return {label: (dataset.hidden is falsy, isDatasetVisible(i))} for a chart."""
    return page.evaluate(
        "(id) => { const c = Chart.getChart(id);"
        " return Object.fromEntries(c.data.datasets.map((d, i) => [d.label, [!d.hidden, c.isDatasetVisible(i)]])); }",
        canvas_id,
    )


@pytest.mark.e2e
def test_chart_selection_toggles_follow_the_isolate_truth_table(page: Page):
    """`window.toggleChartSelection(name)` drives a single shared selection
    of container names that governs both the CPU and Memory history charts.

    An empty selection means "all visible". Regression guard for issue #256,
    which replaces the Chart.js canvas legend with a selection driven from
    the Monitor container table.
    """
    open_monitor_pane(
        page,
        history=THREE_CONTAINER_HISTORY,
        servers=[(101, "srv-a")],
    )

    inject_stats(page, 101, "srv-a", [WEB_CONTAINER, DB_CONTAINER, CACHE_CONTAINER])
    select_injected_server(page, 101, 2)
    wait_for_chart_series(page, 3)

    def assert_step(step, expected_visible):
        expected = {
            name: (True, True) if name in expected_visible else (False, False)
            for name in ("web", "db", "cache")
        }
        for canvas_id, chart_name in (
            ("cpu-history-chart", "CPU"),
            ("mem-history-chart", "Memory"),
        ):
            actual = _chart_visibility_map(page, canvas_id)
            actual = {name: tuple(value) for name, value in actual.items()}
            assert actual == expected, (
                f"step {step} ({chart_name} chart): expected {expected}, got {actual}"
            )

    # Step 1: all visible -> click web -> web only.
    page.evaluate("(n) => window.toggleChartSelection(n)", "web")
    assert_step(1, {"web"})

    # Step 2: {web} -> click db -> web, db.
    page.evaluate("(n) => window.toggleChartSelection(n)", "db")
    assert_step(2, {"web", "db"})

    # Step 3: {web, db} -> click web -> db only.
    page.evaluate("(n) => window.toggleChartSelection(n)", "web")
    assert_step(3, {"db"})

    # Step 4: {db} -> click db -> all three (reset path).
    page.evaluate("(n) => window.toggleChartSelection(n)", "db")
    assert_step(4, {"web", "db", "cache"})


@pytest.mark.e2e
def test_monitor_filter_narrows_glance_bar_and_shows_match_count(page: Page):
    """The glance bar must count only containers matching the filter, and the
    "N of M shown" indicator must report the match count.

    Regression guard for issue #259: the glance bar previously received
    unfiltered data, so its totals described the whole server while the table
    and charts showed a subset.
    """
    open_monitor_pane(page, history=[], servers=[(201, "Server A")])

    units = [
        {"unit": "web.service", "scope": "user", "load_state": "loaded", "active_state": "active", "sub_state": "running", "n_restarts": 0},
        {"unit": "db.service", "scope": "user", "load_state": "loaded", "active_state": "active", "sub_state": "running", "n_restarts": 0},
        {"unit": "cache.service", "scope": "user", "load_state": "loaded", "active_state": "active", "sub_state": "running", "n_restarts": 0},
    ]
    inject_stats(page, 201, "Server A", [WEB_CONTAINER, DB_CONTAINER, CACHE_CONTAINER], units=units)
    select_injected_server(page, 201, option_count=2)

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
def test_switching_between_three_servers_renders_each_selection(page: Page):
    """Selecting a different server in the Monitor dropdown must always
    re-render the stats table for that server, even after the Editor file
    tree has claimed a server id via `window.setActiveServer`.

    Regression guard for issue #365: the Monitor pane keys some of its
    rendering on the global `window.activeServerId`, which the Editor file
    tree also writes, instead of the dropdown's own
    `window._monitoringServerId`. This test drives the dropdown through the
    normal selection path and lets the Editor claim a server id via
    `window.setActiveServer` partway through. The injected
    server ids (101-103) cannot collide with the auto-seeded "Mock Server"
    (id 1), so no real SSE traffic can repaint them underneath the
    assertions.
    """
    open_monitor_pane(
        page,
        history=[],
        servers=[(101, "alpha"), (102, "beta"), (103, "gamma")],
    )

    # Claim a sentinel server id (matching none of the injected ones below)
    # so the first injected stats frame cannot auto-adopt as the active
    # server (main.js only does that while window.activeServerId is still
    # null), leaving the Editor/Monitor divergence at step 4 as the only
    # thing under test.
    page.evaluate("window.setActiveServer(999)")

    inject_stats(page, 101, "alpha", [WEB_CONTAINER])
    inject_stats(page, 102, "beta", [DB_CONTAINER])
    inject_stats(page, 103, "gamma", [CACHE_CONTAINER])

    page.wait_for_function(
        "['101', '102', '103'].every(v => "
        "Array.from(document.getElementById('monitoring-server-select').options)"
        ".some(o => o.value === v))"
    )

    table = page.locator("#monitoring-stats-table")

    # Select alpha (101) through the dropdown.
    select_injected_server(page, 101, 4)
    expect(table).to_contain_text("web")
    expect(table).not_to_contain_text("db")
    expect(table).not_to_contain_text("cache")

    # The Editor file tree claims server 102, writing window.activeServerId
    # directly, the way it does when a user browses files for a different
    # server than the one shown in the Monitor dropdown.
    page.evaluate("window.setActiveServer(102)")

    # Select beta (102) through the dropdown. This must repaint the table
    # for beta even though window.activeServerId already equals 102.
    select_injected_server(page, 102, 4)
    expect(table).to_contain_text("db")
    expect(table).not_to_contain_text("web")
    expect(table).not_to_contain_text("cache")

    # Select gamma (103) through the dropdown.
    select_injected_server(page, 103, 4)
    expect(table).to_contain_text("cache")
    expect(table).not_to_contain_text("web")
    expect(table).not_to_contain_text("db")


@pytest.mark.e2e
def test_glance_bar_counts_come_from_unit_state(page: Page):
    """TOTAL, RUNNING and STOPPED must be derived from the `units` array in
    the stats payload, not from the containers list.

    Regression guard for issue #258: the old Set-based derivation
    (`allSeenContainersBySid`, seeded only from running containers) would
    report 1 / 1 / 0 from the stray container alone, ignoring the actual
    Quadlet unit state entirely.
    """
    open_monitor_pane(page, history=[], servers=[(999, "Server Synthetic")])

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


@pytest.mark.e2e
def test_table_lists_units_that_have_no_running_container(page: Page):
    """A stopped or failed unit must still get a table row, so the list says
    which Quadlet is missing instead of silently dropping it.

    Regression guard for issue #372: the table was built from the containers
    array alone, which `podman ps` fills with running containers only.
    """
    open_monitor_pane(page, history=[], servers=[(301, "Server Merged")])

    web = dict(WEB_CONTAINER, unit="web.service")
    units = [
        {"unit": "web.service", "scope": "user", "load_state": "loaded", "active_state": "active", "sub_state": "running", "n_restarts": 0},
        {"unit": "cache.service", "scope": "user", "load_state": "loaded", "active_state": "inactive", "sub_state": "dead", "n_restarts": 0},
        {"unit": "api.service", "scope": "user", "load_state": "loaded", "active_state": "failed", "sub_state": "failed", "n_restarts": 2},
    ]

    inject_stats(page, 301, "Server Merged", [web], units=units)
    select_injected_server(page, 301, option_count=2)

    rows = page.locator("#monitoring-stats-table table tbody tr")
    expect(rows).to_have_count(3)

    # The stopped and failed units carry their systemd state as the status
    # badge, never the "running" badge a container row would get.
    expect(rows.filter(has_text="cache")).to_contain_text("inactive")
    expect(rows.filter(has_text="api")).to_contain_text("failed")
    expect(rows.filter(has_text="cache")).not_to_contain_text("running")


@pytest.mark.e2e
def test_a_container_missing_its_unit_label_is_not_listed_twice(page: Page):
    """A running container whose PODMAN_SYSTEMD_UNIT label is absent still
    claims its unit, so merging units into the table cannot duplicate it.

    The join falls back to the container name stem, which Quadlet derives the
    container name from unless ContainerName= overrides it.
    """
    open_monitor_pane(page, history=[], servers=[(302, "Server Unlabelled")])

    units = [
        {"unit": "web.service", "scope": "user", "load_state": "loaded", "active_state": "active", "sub_state": "running", "n_restarts": 0},
    ]

    inject_stats(page, 302, "Server Unlabelled", [WEB_CONTAINER], units=units)
    select_injected_server(page, 302, option_count=2)

    rows = page.locator("#monitoring-stats-table table tbody tr")
    expect(rows).to_have_count(1)
    expect(rows.filter(has_text="web")).to_have_count(1)


@pytest.mark.e2e
def test_dropdown_lists_a_server_that_has_never_sent_stats(page: Page):
    """The dropdown is inventory, not telemetry.

    Regression guard for issue #365: options used to be built from the
    `lastStatsPerServer` cache, so a server appeared only after its first
    stats frame. They now come from the database via /api/servers/options,
    which is what lets the list stay still while stats stream in.
    """
    open_monitor_pane(page, history=[], servers=[(101, "alpha")])

    select = page.locator("#monitoring-server-select")
    expect(select.locator('option[value="101"]')).to_have_count(1)

    # No stats frame has ever been injected for 101.
    select_injected_server(page, 101, option_count=2)
    expect(page.locator("#monitoring-stats-table")).to_contain_text(
        "Waiting for stats data"
    )


@pytest.mark.e2e
def test_stats_frames_never_touch_the_server_dropdown(page: Page):
    """No stats frame may add, remove or relabel an `<option>`.

    Regression guard for issue #365. The user-visible symptom is a swallowed
    click: rebuilding the option list while the native dropdown is open
    invalidates the browser's popup, so `change` never fires. Playwright's
    `select_option` sets the value directly and never opens that popup, so the
    symptom itself is untestable here. The mutation is the cause, and it is
    observable, so that is what this asserts.
    """
    open_monitor_pane(page, history=[], servers=[(101, "alpha"), (102, "beta")])

    page.wait_for_function(
        "document.getElementById('monitoring-server-select').options.length === 3"
    )

    page.evaluate(
        """() => {
            window._selectMutations = 0;
            const sel = document.getElementById('monitoring-server-select');
            new MutationObserver(function(records) {
                window._selectMutations += records.length;
            }).observe(sel, { childList: true, subtree: true, characterData: true });
        }"""
    )

    inject_stats(page, 101, "alpha", [WEB_CONTAINER])
    inject_stats(page, 102, "beta", [DB_CONTAINER])
    inject_stats(page, 101, "alpha", [WEB_CONTAINER, DB_CONTAINER])

    assert page.evaluate("window._selectMutations") == 0


@pytest.mark.e2e
def test_stats_error_for_another_server_leaves_the_monitor_table_alone(page: Page):
    """A `stats_error` may only repaint the pane whose server it names.

    The handler paints two tables owned by two different ids: the Editor's
    `#stats-table` follows `window.activeServerId`, the Monitor's
    `#monitoring-stats-table` follows `window._monitoringServerId`. Both were
    unguarded, so any server's error wiped both panes. Only the Monitor half
    is asserted here: `#stats-table` is not in the rendered dashboard.
    """
    open_monitor_pane(page, history=[], servers=[(101, "alpha"), (102, "beta")])

    inject_stats(page, 101, "alpha", [WEB_CONTAINER])
    select_injected_server(page, 101, option_count=3)
    expect(page.locator("#monitoring-stats-table")).to_contain_text("web")

    # The Editor is pointed at a different server than the Monitor.
    page.evaluate("window.setActiveServer(102)")
    page.evaluate(
        """() => window.handleStatsError({
            data: JSON.stringify({
                server_id: 102,
                server_name: 'beta',
                error: 'connection refused',
            })
        })"""
    )

    # Server 102's failure is not the Monitor's to show.
    expect(page.locator("#monitoring-stats-table")).to_contain_text("web")
    expect(page.locator("#monitoring-stats-table")).not_to_contain_text(
        "connection refused"
    )

    # The selected server's own failure does reach the Monitor pane.
    page.evaluate(
        """() => window.handleStatsError({
            data: JSON.stringify({
                server_id: 101,
                server_name: 'alpha',
                error: 'podman timed out',
            })
        })"""
    )
    expect(page.locator("#monitoring-stats-table")).to_contain_text("podman timed out")


@pytest.mark.e2e
def test_reload_servers_swap_keeps_the_monitor_selection(page: Page):
    """Refreshing the server inventory must not clear the user's selection.

    The select is swapped by HTMX on the body's `reload-servers` event, which
    replaces its options. The selection has to be re-applied afterwards, and
    without a spurious re-render of the pane.
    """
    open_monitor_pane(page, history=[], servers=[(101, "alpha"), (102, "beta")])

    inject_stats(page, 101, "alpha", [WEB_CONTAINER])
    select_injected_server(page, 101, option_count=3)
    expect(page.locator("#monitoring-stats-table")).to_contain_text("web")

    page.evaluate("() => htmx.trigger(document.body, 'reload-servers')")
    page.wait_for_function(
        "document.getElementById('monitoring-server-select').options.length === 3"
    )

    expect(page.locator("#monitoring-server-select")).to_have_value("101")
    expect(page.locator("#monitoring-content")).to_be_visible()
    expect(page.locator("#monitoring-stats-table")).to_contain_text("web")


@pytest.mark.e2e
def test_monitor_keeps_updating_after_a_container_disappears(page: Page):
    """The stats table must repaint when a container drops out of a later
    stats frame, even after both containers have already been charted.

    Regression guard for issue #370: appending to the CPU/Memory history
    charts throws inside appendToChart (Chart.js `this.getDataset() is
    undefined`) when a previously-charted container is missing from the new
    frame, which aborts updateMonitoringView before the table is repainted.
    """
    open_monitor_pane(
        page,
        history=TWO_CONTAINER_HISTORY,
        servers=[(1, "alpha")],
    )

    select_injected_server(page, 1, option_count=2)

    # Both containers are charted before the one that disappears is dropped.
    inject_stats(page, 1, "alpha", [WEB_CONTAINER, DB_CONTAINER])
    wait_for_chart_series(page, 2)

    # A later frame drops "web" entirely.
    inject_stats(page, 1, "alpha", [DB_CONTAINER])

    assert_only_row(page, "db")


@pytest.mark.e2e
def test_saved_server_restores_before_any_stats_arrive(page: Page):
    """The `qm-monitor-server` restore keys on the option, not on the cache.

    It used to require an entry in `lastStatsPerServer`, so a reload landed on
    the empty state until the saved server's next stats frame. The pane
    already renders a "Waiting for stats data..." placeholder for that case.
    """
    page.add_init_script("localStorage.setItem('qm-monitor-server', '101')")

    open_monitor_pane(page, history=[], servers=[(101, "alpha")])

    expect(page.locator("#monitoring-server-select")).to_have_value("101")
    expect(page.locator("#monitoring-content")).to_be_visible()
    expect(page.locator("#monitoring-stats-table")).to_contain_text(
        "Waiting for stats data"
    )


@pytest.mark.e2e
def test_swatch_click_isolates_the_container_on_both_charts(page: Page):
    """Clicking a row's chart-swatch button isolates that container's series
    on both history charts, and the swatch buttons reflect the selection via
    `aria-pressed` and the `chart-swatch-off` class.

    Regression guard for issue #256, which replaces the Chart.js canvas
    legend with the container table as the selector for the two history
    charts.
    """
    open_monitor_pane(
        page,
        history=THREE_CONTAINER_HISTORY,
        servers=[(101, "srv-a")],
    )

    inject_stats(page, 101, "srv-a", [WEB_CONTAINER, DB_CONTAINER, CACHE_CONTAINER])
    select_injected_server(page, 101, 2)
    wait_for_chart_series(page, 3)

    page.click('#monitoring-stats-table button.chart-swatch[data-container="web"]')

    expected = {
        "web": (True, True),
        "db": (False, False),
        "cache": (False, False),
    }
    for canvas_id, chart_name in (
        ("cpu-history-chart", "CPU"),
        ("mem-history-chart", "Memory"),
    ):
        actual = _chart_visibility_map(page, canvas_id)
        actual = {name: tuple(value) for name, value in actual.items()}
        assert actual == expected, (
            f"{chart_name} chart: expected {expected}, got {actual}"
        )

    web_swatch = page.locator(
        '#monitoring-stats-table button.chart-swatch[data-container="web"]'
    )
    db_swatch = page.locator(
        '#monitoring-stats-table button.chart-swatch[data-container="db"]'
    )
    cache_swatch = page.locator(
        '#monitoring-stats-table button.chart-swatch[data-container="cache"]'
    )

    expect(web_swatch).to_have_attribute("aria-pressed", "true")
    expect(web_swatch).not_to_contain_class("chart-swatch-off")

    expect(db_swatch).to_have_attribute("aria-pressed", "false")
    expect(db_swatch).to_contain_class("chart-swatch-off")

    expect(cache_swatch).to_have_attribute("aria-pressed", "false")
    expect(cache_swatch).to_contain_class("chart-swatch-off")


@pytest.mark.e2e
def test_theme_toggle_survives_the_disabled_canvas_legend(page: Page):
    """The history charts set `plugins.legend: {display: false}` (issue #256),
    but `patchChartOptions` still writes `plugins.legend.labels.color` on every
    theme switch. Guards against that path throwing, which is how the bug in
    test_editor_theme_follow_e2e.py originally presented."""
    open_monitor_pane(page, history=THREE_CONTAINER_HISTORY, servers=[(101, "srv-a")])
    inject_stats(page, 101, "srv-a", [WEB_CONTAINER, DB_CONTAINER, CACHE_CONTAINER])
    select_injected_server(page, 101, 2)
    wait_for_chart_series(page, 3)

    before = page.evaluate("document.documentElement.getAttribute('data-theme')")
    result = page.evaluate(
        "() => { try { window.toggleTheme(); return 'ok'; }"
        " catch (e) { return String(e); } }"
    )
    assert result == "ok", f"toggleTheme threw with the monitor charts up: {result}"

    after = page.evaluate("document.documentElement.getAttribute('data-theme')")
    # Restore before asserting: the e2e fixtures are package-scoped, so a theme
    # left flipped here leaks into every test that runs after this one.
    page.evaluate("() => window.toggleTheme()")
    assert after != before, f"theme did not change: {before!r} -> {after!r}"


@pytest.mark.e2e
def test_history_charts_have_no_canvas_legend(page: Page):
    """The CPU/Memory history charts must not render the built-in Chart.js
    legend, since the container table now drives series selection (#256).
    """
    open_monitor_pane(
        page,
        history=THREE_CONTAINER_HISTORY,
        servers=[(101, "srv-a")],
    )

    inject_stats(page, 101, "srv-a", [WEB_CONTAINER, DB_CONTAINER, CACHE_CONTAINER])
    select_injected_server(page, 101, 2)
    wait_for_chart_series(page, 3)

    for canvas_id in ("cpu-history-chart", "mem-history-chart"):
        legend_display = page.evaluate(
            "(id) => { const c = Chart.getChart(id);"
            " const legend = c && c.options && c.options.plugins && c.options.plugins.legend;"
            " if (!legend) return 'MISSING'; return legend.display; }",
            canvas_id,
        )
        assert legend_display is False, (
            f"{canvas_id}: expected legend.display === False, got {legend_display!r}"
        )


@pytest.mark.e2e
def test_changing_the_filter_resets_the_chart_selection(page: Page):
    """Changing the container filter must clear the chart selection, so no
    surviving dataset stays hidden because of a stale isolate/selection made
    before the filter changed.

    Regression guard for issue #256.
    """
    open_monitor_pane(
        page,
        history=THREE_CONTAINER_HISTORY,
        servers=[(101, "srv-a")],
    )

    inject_stats(page, 101, "srv-a", [WEB_CONTAINER, DB_CONTAINER, CACHE_CONTAINER])
    select_injected_server(page, 101, 2)
    wait_for_chart_series(page, 3)

    # Isolate "web" first, so "db" is hidden and the test can't pass vacuously.
    page.click('#monitoring-stats-table button.chart-swatch[data-container="web"]')

    db_visible = page.evaluate(
        "() => { const c = Chart.getChart('cpu-history-chart');"
        " const i = c.data.datasets.findIndex(d => d.label === 'db');"
        " return i === -1 ? null : !c.data.datasets[i].hidden; }"
    )
    assert db_visible is False, (
        f"expected 'db' to be hidden after isolating 'web', got {db_visible!r}"
    )

    # Change the filter to something that matches "web" and "cache", not "db".
    page.evaluate(
        """() => {
            const input = document.getElementById('monitor-container-filter');
            input.value = 'e';
            input.dispatchEvent(new Event('input', { bubbles: true }));
        }"""
    )

    for canvas_id, chart_name in (
        ("cpu-history-chart", "CPU"),
        ("mem-history-chart", "Memory"),
    ):
        hidden_flags = page.evaluate(
            f"() => Chart.getChart('{canvas_id}').data.datasets.map(d => [d.label, !!d.hidden])"
        )
        for label, hidden in hidden_flags:
            assert not hidden, (
                f"{chart_name} chart: dataset {label!r} still hidden after filter change: "
                f"{hidden_flags}"
            )
