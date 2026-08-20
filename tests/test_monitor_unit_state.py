"""Tests for surfacing systemd unit state in the Monitor tab (Issue #266).

Covers:
- static/main.js defines buildUnitIndex(units), which returns null when units
  is null/undefined and otherwise indexes the units array by unit name.
- static/main.js defines getUnitBadgeInfo(activeState) mapping 'failed' /
  'active' / anything else to unit-failed / unit-active / unit-other badge
  classes, with the state string itself as the label.
- renderContainerRow accepts a unit index as a second parameter and renders a
  unit cell: STAT_PLACEHOLDER when there is no match, otherwise a stat-badge
  span, plus a restart count with a visually-hidden label when n_restarts > 0.
- renderContainerStatsTable's headers array includes a Unit column and passes
  an index built from data.units into renderContainerRow.
- computeUnitCounts also returns a failed count (STAT_PLACEHOLDER when units
  is null/undefined), leaving stopped as total - running.
- main.js defines renderFailedStat(failed), following renderUnhealthyStat's
  shape, and updateSummaryStrip calls it.
- templates/dashboard.html has a mstat-failed monitor-stat-block inside the
  health monitor-stat-group, labelled "Failed".
- static/style.css defines .stat-badge.unit-failed / .unit-active / .unit-other.
"""
import os
import re

import pytest

JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "main.js")
DASHBOARD_HTML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "dashboard.html"
)
STYLE_CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")


def _js():
    with open(JS_PATH, encoding="utf-8") as f:
        return f.read()


def _dashboard_html():
    with open(DASHBOARD_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _style_css():
    with open(STYLE_CSS_PATH, encoding="utf-8") as f:
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


class TestBuildUnitIndex:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_build_unit_index_function_defined(self):
        assert "function buildUnitIndex(" in self.js, (
            "expected main.js to define a buildUnitIndex function"
        )

    @pytest.mark.unit
    def test_build_unit_index_returns_null_when_units_missing(self):
        match = _extract_function_body(self.js, "buildUnitIndex")
        assert match, "expected to find buildUnitIndex function body in main.js"
        body = match.group(0)
        assert re.search(r"(undefined|null)", body), (
            "expected buildUnitIndex to guard against null/undefined units"
        )
        assert re.search(r"return\s+null", body), (
            "expected buildUnitIndex to return null when units is null/undefined"
        )

    @pytest.mark.unit
    def test_build_unit_index_keys_by_unit_name(self):
        match = _extract_function_body(self.js, "buildUnitIndex")
        assert match, "expected to find buildUnitIndex function body in main.js"
        body = match.group(0)
        assert re.search(r"\.unit\b", body), (
            "expected buildUnitIndex to key the index off the unit's .unit field"
        )


class TestGetUnitBadgeInfo:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_get_unit_badge_info_function_defined(self):
        assert "function getUnitBadgeInfo(" in self.js, (
            "expected main.js to define a getUnitBadgeInfo function"
        )

    @pytest.mark.unit
    def test_get_unit_badge_info_maps_failed_active_other(self):
        match = _extract_function_body(self.js, "getUnitBadgeInfo")
        assert match, "expected to find getUnitBadgeInfo function body in main.js"
        body = match.group(0)
        assert "'failed'" in body or '"failed"' in body, (
            "expected getUnitBadgeInfo to check for the failed state"
        )
        assert "unit-failed" in body, (
            "expected getUnitBadgeInfo to map failed to the unit-failed badge class"
        )
        assert "'active'" in body or '"active"' in body, (
            "expected getUnitBadgeInfo to check for the active state"
        )
        assert "unit-active" in body, (
            "expected getUnitBadgeInfo to map active to the unit-active badge class"
        )
        assert "unit-other" in body, (
            "expected getUnitBadgeInfo to fall back to the unit-other badge class"
        )


class TestRenderContainerRowUnitCell:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_render_container_row_accepts_unit_index_param(self):
        assert re.search(
            r"function renderContainerRow\(\s*c\s*,\s*\w+\s*\)", self.js
        ), (
            "expected renderContainerRow to accept a second unit index parameter"
        )

    @pytest.mark.unit
    def test_render_container_row_uses_stat_placeholder_for_missing_unit(self):
        match = _extract_function_body(self.js, "renderContainerRow")
        assert match, "expected to find renderContainerRow function body in main.js"
        body = match.group(0)
        assert "STAT_PLACEHOLDER" in body, (
            "expected renderContainerRow to fall back to STAT_PLACEHOLDER "
            "when there is no matching unit"
        )

    @pytest.mark.unit
    def test_render_container_row_renders_unit_badge(self):
        match = _extract_function_body(self.js, "renderContainerRow")
        assert match, "expected to find renderContainerRow function body in main.js"
        body = match.group(0)
        assert "getUnitBadgeInfo" in body, (
            "expected renderContainerRow to call getUnitBadgeInfo"
        )
        assert "stat-badge" in body, (
            "expected renderContainerRow to render the unit state as a stat-badge span"
        )

    @pytest.mark.unit
    def test_render_container_row_shows_restart_count_with_hidden_label(self):
        match = _extract_function_body(self.js, "renderContainerRow")
        assert match, "expected to find renderContainerRow function body in main.js"
        body = match.group(0)
        assert "n_restarts" in body, (
            "expected renderContainerRow to reference n_restarts"
        )
        assert "visually-hidden" in body, (
            "expected renderContainerRow to add a visually-hidden label for restarts"
        )
        assert re.search(r"restart", body, re.IGNORECASE), (
            "expected the visually-hidden label to name the count as restarts"
        )


class TestRenderContainerStatsTableUnitColumn:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_headers_include_unit_column(self):
        match = _extract_function_body(self.js, "renderContainerStatsTable")
        assert match, (
            "expected to find renderContainerStatsTable function body in main.js"
        )
        body = match.group(0)
        assert re.search(r"text:\s*['\"]Unit['\"]", body), (
            "expected renderContainerStatsTable's headers array to include a "
            "Unit column"
        )

    @pytest.mark.unit
    def test_passes_unit_index_built_from_data_units_to_render_container_row(self):
        match = _extract_function_body(self.js, "renderContainerStatsTable")
        assert match, (
            "expected to find renderContainerStatsTable function body in main.js"
        )
        body = match.group(0)
        assert "buildUnitIndex" in body, (
            "expected renderContainerStatsTable to call buildUnitIndex"
        )
        assert re.search(r"buildUnitIndex\(\s*data\.units\s*\)", body), (
            "expected renderContainerStatsTable to build the unit index from "
            "data.units"
        )
        assert re.search(r"renderContainerRow\(\s*c\s*,\s*\w+\s*\)", body), (
            "expected renderContainerStatsTable to pass the unit index into "
            "renderContainerRow"
        )


class TestComputeUnitCountsFailed:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_returns_failed_placeholder_when_units_missing(self):
        match = _extract_function_body(self.js, "computeUnitCounts")
        assert match, "expected to find computeUnitCounts function body in main.js"
        body = match.group(0)
        assert re.search(r"failed:\s*STAT_PLACEHOLDER", body), (
            "expected computeUnitCounts to return failed: STAT_PLACEHOLDER when "
            "units is null/undefined"
        )

    @pytest.mark.unit
    def test_counts_failed_units_by_active_state(self):
        match = _extract_function_body(self.js, "computeUnitCounts")
        assert match, "expected to find computeUnitCounts function body in main.js"
        body = match.group(0)
        assert re.search(r"active_state\s*===\s*['\"]failed['\"]", body), (
            "expected computeUnitCounts to count units whose active_state is failed"
        )

    @pytest.mark.unit
    def test_stopped_remains_total_minus_running_alongside_failed(self):
        match = _extract_function_body(self.js, "computeUnitCounts")
        assert match, "expected to find computeUnitCounts function body in main.js"
        body = match.group(0)
        assert re.search(
            r"stopped:\s*total\s*-\s*running\s*,\s*failed:\s*failed", body
        ), (
            "expected the returned object to keep stopped: total - running "
            "unchanged while also returning the new failed count"
        )


class TestRenderFailedStat:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_render_failed_stat_function_defined(self):
        assert "function renderFailedStat(" in self.js, (
            "expected main.js to define a renderFailedStat function"
        )

    @pytest.mark.unit
    def test_render_failed_stat_toggles_danger_and_appends_flag(self):
        match = _extract_function_body(self.js, "renderFailedStat")
        assert match, "expected to find renderFailedStat function body in main.js"
        body = match.group(0)
        assert "mstat-failed" in body, (
            "expected renderFailedStat to target the mstat-failed element"
        )
        assert re.search(r"classList\.toggle\(\s*['\"]danger['\"]", body), (
            "expected renderFailedStat to toggle the danger class"
        )
        assert "monitor-stat-flag" in body, (
            "expected renderFailedStat to append a monitor-stat-flag glyph span"
        )

    @pytest.mark.unit
    def test_update_summary_strip_calls_render_failed_stat(self):
        match = _extract_function_body(self.js, "updateSummaryStrip")
        assert match, "expected to find updateSummaryStrip function body in main.js"
        body = match.group(0)
        assert "renderFailedStat" in body, (
            "expected updateSummaryStrip to call renderFailedStat"
        )


class TestDashboardHtmlFailedStatBlock:
    def setup_method(self):
        self.html = _dashboard_html()

    @pytest.mark.unit
    def test_mstat_failed_block_present_in_health_group(self):
        match = re.search(
            r'<ul class="monitor-stat-group">.*?id="mstat-unhealthy".*?</ul>',
            self.html,
            re.DOTALL,
        )
        assert match, (
            "expected to find the health monitor-stat-group containing "
            "mstat-unhealthy in dashboard.html"
        )
        block = match.group(0)
        assert 'id="mstat-failed"' in block, (
            "expected a mstat-failed element inside the health monitor-stat-group"
        )

    @pytest.mark.unit
    def test_mstat_failed_labelled_failed(self):
        match = re.search(
            r'id="mstat-failed".*?monitor-stat-lbl">([^<]*)<',
            self.html,
            re.DOTALL,
        )
        assert match, "expected to find the mstat-failed label text in dashboard.html"
        assert match.group(1).strip() == "Failed", (
            "expected the mstat-failed stat block to be labelled 'Failed'"
        )


class TestStyleCssUnitBadgeClasses:
    def setup_method(self):
        self.css = _style_css()

    @pytest.mark.unit
    def test_unit_failed_badge_class_defined(self):
        assert re.search(r"\.stat-badge\.unit-failed\s*\{", self.css), (
            "expected style.css to define .stat-badge.unit-failed"
        )

    @pytest.mark.unit
    def test_unit_active_badge_class_defined(self):
        assert re.search(r"\.stat-badge\.unit-active\s*\{", self.css), (
            "expected style.css to define .stat-badge.unit-active"
        )

    @pytest.mark.unit
    def test_unit_other_badge_class_defined(self):
        assert re.search(r"\.stat-badge\.unit-other\s*\{", self.css), (
            "expected style.css to define .stat-badge.unit-other"
        )
