"""Tests for the Monitor tab total CPU + MEM usage per server (Issue #189).

Covers:
- static/main.js defines a computeServerTotals(containers) helper that sums
  container cpu/mem percentages using parsePercent().
- static/main.js's updateSummaryStrip calls computeServerTotals and renders
  the results into #mstat-cpu / #mstat-mem elements.
- templates/dashboard.html's monitor-stat-bar contains id="mstat-cpu" and
  id="mstat-mem" elements to display the aggregated totals.
"""
import os
import re

import pytest

from tests.js_source import read_static_js

DASHBOARD_HTML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "dashboard.html"
)


def _js():
    return read_static_js()


def _dashboard_html():
    with open(DASHBOARD_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _extract_function_body(js, name):
    """Extract a top-level function's body, from its declaration up to the
    next top-level `function ` or `window.` declaration (mirrors the
    approach used in test_editor_unsaved_indicator.py)."""
    match = re.search(
        r"function " + re.escape(name) + r"\([^)]*\)\s*\{.*?(?=\nfunction |\nwindow\.)",
        js,
        re.DOTALL,
    )
    return match


class TestComputeServerTotals:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_compute_server_totals_function_defined(self):
        assert "function computeServerTotals(" in self.js, (
            "expected main.js to define a computeServerTotals function"
        )

    @pytest.mark.unit
    def test_compute_server_totals_uses_parse_percent_for_cpu_and_mem(self):
        match = _extract_function_body(self.js, "computeServerTotals")
        assert match, "expected to find computeServerTotals function body in main.js"
        body = match.group(0)
        assert "parsePercent" in body
        assert re.search(r"parsePercent\(\s*\w+\.cpu\s*\)", body), (
            "expected computeServerTotals to call parsePercent on a .cpu field"
        )
        assert re.search(r"parsePercent\(\s*\w+\.mem\s*\)", body), (
            "expected computeServerTotals to call parsePercent on a .mem field"
        )


class TestUpdateSummaryStripTotals:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_update_summary_strip_uses_compute_server_totals_and_renders_ids(self):
        match = _extract_function_body(self.js, "updateSummaryStrip")
        assert match, "expected to find updateSummaryStrip function body in main.js"
        body = match.group(0)
        assert "computeServerTotals" in body, (
            "expected updateSummaryStrip to call computeServerTotals"
        )
        assert "mstat-cpu" in body, (
            "expected updateSummaryStrip to reference the mstat-cpu element id"
        )
        assert "mstat-mem" in body, (
            "expected updateSummaryStrip to reference the mstat-mem element id"
        )


class TestDashboardHtmlMonitorStatBar:
    def setup_method(self):
        self.html = _dashboard_html()

    @pytest.mark.unit
    def test_monitor_stat_bar_contains_cpu_and_mem_stat_elements(self):
        match = re.search(
            r'<div id="monitor-stat-bar".*?(?=<div id="monitoring-content")',
            self.html,
            re.DOTALL,
        )
        assert match, "expected to find the monitor-stat-bar div in dashboard.html"
        block = match.group(0)
        assert 'id="mstat-cpu"' in block, (
            "expected a mstat-cpu element inside monitor-stat-bar"
        )
        assert 'id="mstat-mem"' in block, (
            "expected a mstat-mem element inside monitor-stat-bar"
        )
