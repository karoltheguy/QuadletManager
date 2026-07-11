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


def _js():
    with open(JS_PATH, encoding="utf-8") as f:
        return f.read()


def _html():
    with open(HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _css():
    with open(CSS_PATH, encoding="utf-8") as f:
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
