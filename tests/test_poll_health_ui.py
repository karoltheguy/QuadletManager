import pytest
"""
Tests for the quadlet-tree poll-health warning badge (Issue #185).
Covers:
- server row markup includes a hidden .server-poll-warning badge span
- connectSSE registers a 'poll_health' SSE listener
- updatePollHealth ignores non-server-scope payloads, tracks state, and
  shows/hides the badge with a tooltip
- initial snapshot is fetched from /api/poll-health and applied
- badges are re-applied after htmx:afterSwap tree reloads
- CSS rule exists for .server-poll-warning
"""
import os
import re

JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "main.js")
HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "templates", "partials", "servers_list.html")
CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")
DASHBOARD_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")


def _js():
    with open(JS_PATH, encoding="utf-8") as f:
        return f.read()


def _html():
    with open(HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _css():
    with open(CSS_PATH, encoding="utf-8") as f:
        return f.read()


def _dashboard_html():
    with open(DASHBOARD_HTML_PATH, encoding="utf-8") as f:
        return f.read()


class TestServerRowBadgeMarkup:
    def setup_method(self):
        self.html = _html()

    @pytest.mark.unit
    def test_badge_span_class_exists(self):
        assert "server-poll-warning" in self.html

    @pytest.mark.unit
    def test_badge_has_server_id_attribute(self):
        pattern = r'<span[^>]*class="[^"]*server-poll-warning[^"]*"[^>]*data-server-id="\{\{\s*server\[0\]\s*\}\}"'
        assert re.search(pattern, self.html)

    @pytest.mark.unit
    def test_badge_is_hidden_by_default(self):
        pattern = r'<span[^>]*class="[^"]*server-poll-warning[^"]*"[^>]*hidden'
        assert re.search(pattern, self.html)


class TestConnectSSERegistersPollHealth:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_poll_health_listener_registered(self):
        assert "evtSource.addEventListener('poll_health'" in self.js

    @pytest.mark.unit
    def test_poll_health_listener_within_connect_sse(self):
        pattern = r"function connectSSE\(\)[\s\S]{0,2000}evtSource\.addEventListener\('poll_health'"
        assert re.search(pattern, self.js)


class TestPollHealthState:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_poll_health_state_map_declared(self):
        assert "_pollHealthState" in self.js

    @pytest.mark.unit
    def test_update_poll_health_function_exists(self):
        assert re.search(r"function updatePollHealth\s*\(", self.js)

    @pytest.mark.unit
    def test_update_poll_health_checks_scope_is_server(self):
        pattern = r"function updatePollHealth[\s\S]{0,500}data\.scope\s*(===|!==|==|!=)\s*'server'"
        assert re.search(pattern, self.js)


class TestConnectSSEServerScoping:
    """Covers Issue #169: SSE connections should be scoped to the active server
    and reconnect when the active server changes."""

    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_evtsource_hoisted_to_module_scope(self):
        assert re.search(r"^var evtSource = null;", self.js, re.MULTILINE)

    @pytest.mark.unit
    def test_connect_sse_url_includes_active_server_id(self):
        pattern = (
            r"function connectSSE\(\)[\s\S]{0,500}"
            r"'/api/events' \+ \(window\.activeServerId \? "
            r"\('\?server_id=' \+ encodeURIComponent\(window\.activeServerId\)\) : ''\)"
        )
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_set_active_server_reconnects_sse(self):
        pattern = (
            r"window\.setActiveServer = function\(serverId\)[\s\S]{0,500}"
            r"window\.activeServerId = serverId;[\s\S]{0,200}"
            r"evtSource\.close\(\);[\s\S]{0,50}connectSSE\(\);"
        )
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_update_poll_health_stores_state_by_server_id(self):
        pattern = r"function updatePollHealth[\s\S]{0,1500}_pollHealthState\["
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_update_poll_health_queries_badge_by_server_id(self):
        assert ".server-poll-warning[data-server-id=" in self.js

    @pytest.mark.unit
    def test_badge_shown_when_unhealthy(self):
        pattern = r"function updatePollHealth[\s\S]{0,2000}removeAttribute\('hidden'\)"
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_badge_hidden_when_healthy(self):
        pattern = r"function updatePollHealth[\s\S]{0,2000}setAttribute\('hidden'"
        assert re.search(pattern, self.js) or re.search(
            r"function updatePollHealth[\s\S]{0,2000}\.hidden\s*=\s*true", self.js
        )


class TestTooltipStrings:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_polling_failing_tooltip_text(self):
        assert "'Polling failing'" in self.js

    @pytest.mark.unit
    def test_polling_slow_tooltip_text(self):
        assert "'Polling slow'" in self.js


class TestInitialSnapshot:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_fetches_poll_health_snapshot(self):
        assert "fetch('/api/poll-health')" in self.js

    @pytest.mark.unit
    def test_snapshot_iterates_server_keys(self):
        pattern = r"fetch\('/api/poll-health'\)[\s\S]{0,1000}Object\.keys\([\s\S]{0,200}\.servers"
        assert re.search(pattern, self.js)


class TestReapplyOnTreeLoad:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_apply_poll_health_badges_function_exists(self):
        assert re.search(r"function applyPollHealthBadges\s*\(", self.js)

    @pytest.mark.unit
    def test_afterswap_calls_apply_poll_health_badges(self):
        pattern = r"addEventListener\('htmx:afterSwap'[\s\S]{0,1500}applyPollHealthBadges\("
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_snapshot_calls_apply_poll_health_badges(self):
        pattern = r"fetch\('/api/poll-health'\)[\s\S]{0,1500}applyPollHealthBadges\("
        assert re.search(pattern, self.js)


class TestCSSRule:
    def setup_method(self):
        self.css = _css()

    @pytest.mark.unit
    def test_server_poll_warning_rule_exists(self):
        assert re.search(r"\.server-poll-warning\s*\{", self.css)


# ── Sync-Cycle Duration Indicator (Issue #186) ──────────────────────────
class TestSyncCycleIndicatorMarkup:
    def setup_method(self):
        self.html = _dashboard_html()

    @pytest.mark.unit
    def test_sync_cycle_indicator_span_exists(self):
        pattern = r'<span[^>]*id="sync-cycle-indicator"[^>]*class="[^"]*sync-cycle-indicator[^"]*"[^>]*hidden'
        assert re.search(pattern, self.html) or re.search(
            r'<span[^>]*class="[^"]*sync-cycle-indicator[^"]*"[^>]*id="sync-cycle-indicator"[^>]*hidden',
            self.html,
        )

    @pytest.mark.unit
    def test_sync_cycle_indicator_near_monitoring_header(self):
        pattern = r"monitoring-pane[\s\S]{0,600}panel-title[\s\S]{0,600}sync-cycle-indicator"
        assert re.search(pattern, self.html)


class TestUpdateCycleIndicatorFunction:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_update_cycle_indicator_function_exists(self):
        assert re.search(r"function updateCycleIndicator\s*\(", self.js)

    @pytest.mark.unit
    def test_update_cycle_indicator_builds_sync_cycle_text(self):
        pattern = r"function updateCycleIndicator[\s\S]{0,1000}'Sync cycle: '"
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_update_cycle_indicator_formats_with_tofixed(self):
        pattern = r"function updateCycleIndicator[\s\S]{0,1500}\.toFixed\(1\)"
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_update_cycle_indicator_toggles_over_budget_class(self):
        pattern = r"function updateCycleIndicator[\s\S]{0,1500}(cycle-over-budget[\s\S]{0,300}budget_exceeded|budget_exceeded[\s\S]{0,300}cycle-over-budget)"
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_update_cycle_indicator_unhides_indicator(self):
        pattern = r"function updateCycleIndicator[\s\S]{0,1500}removeAttribute\('hidden'\)"
        assert re.search(pattern, self.js)


class TestCycleScopeWiring:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_cycle_scope_routes_to_update_cycle_indicator(self):
        pattern = (
            r"(data\.scope\s*===\s*'cycle'[\s\S]{0,300}updateCycleIndicator\("
            r"|updateCycleIndicator\([\s\S]{0,300}data\.scope\s*===\s*'cycle')"
        )
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_snapshot_calls_update_cycle_indicator(self):
        pattern = (
            r"(fetchPollHealthSnapshot[\s\S]{0,2000}updateCycleIndicator\("
            r"|function fetchPollHealthSnapshot[\s\S]{0,2000}updateCycleIndicator\("
            r"|\.cycle[\s\S]{0,500}updateCycleIndicator\("
            r"|updateCycleIndicator\([\s\S]{0,500}\.cycle)"
        )
        assert re.search(pattern, self.js)


class TestCyclePeriodicRefresh:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_periodic_refresh_interval_registered(self):
        pattern = r"setInterval\([\s\S]{0,300}30000\)|setInterval\([\s\S]{0,300}30000[\s\S]{0,100}\)"
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_periodic_refresh_near_poll_health_snapshot(self):
        pattern = r"setInterval\([\s\S]{0,600}fetchPollHealthSnapshot|fetchPollHealthSnapshot[\s\S]{0,600}setInterval\("
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_periodic_refresh_gated_on_monitoring_pane_visible(self):
        pattern = r"setInterval\([\s\S]{0,1200}monitoring-pane"
        assert re.search(pattern, self.js)


class TestCycleIndicatorCSSRules:
    def setup_method(self):
        self.css = _css()

    @pytest.mark.unit
    def test_sync_cycle_indicator_rule_exists(self):
        assert re.search(r"\.sync-cycle-indicator\s*\{", self.css)

    @pytest.mark.unit
    def test_cycle_over_budget_rule_exists(self):
        assert re.search(
            r"\.cycle-over-budget\s*\{|\.sync-cycle-indicator\.cycle-over-budget\s*\{", self.css
        )
