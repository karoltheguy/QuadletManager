"""Tests for surfacing stopped/failed quadlet units in the Monitor tab (Issue #372).

Covers:
- static/main.js defines mergeUnitRows(containers, units), which returns the
  containers unchanged when units is null/undefined (mirroring the null guard
  in buildUnitIndex).
- mergeUnitRows synthesizes extra rows for units with no matching running
  container, flagging them with a not_running marker, keyed off the unit stem
  (unit name with the trailing .service suffix stripped).
- updateMonitoringView calls mergeUnitRows to build the rows it hands to
  renderContainerStatsTable.
- renderContainerRow uses the not_running flag to source a non-running row's
  Status badge from getUnitBadgeInfo instead of getHealthBadgeInfo.
"""
import os
import re

import pytest

JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "main.js")


def _js():
    with open(JS_PATH, encoding="utf-8") as f:
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


class TestMergeUnitRowsDefined:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_merge_unit_rows_function_defined(self):
        assert "function mergeUnitRows(" in self.js, (
            "expected main.js to define a mergeUnitRows function"
        )

    @pytest.mark.unit
    def test_merge_unit_rows_returns_containers_unchanged_when_units_missing(self):
        match = _extract_function_body(self.js, "mergeUnitRows")
        assert match, "expected to find mergeUnitRows function body in main.js"
        body = match.group(0)
        assert re.search(r"(undefined|null)", body), (
            "expected mergeUnitRows to guard against null/undefined units"
        )
        assert re.search(r"return\s+containers", body), (
            "expected mergeUnitRows to return the containers unchanged when "
            "units is null/undefined"
        )


class TestMergeUnitRowsSynthesizesRows:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_merge_unit_rows_flags_synthesized_rows_not_running(self):
        match = _extract_function_body(self.js, "mergeUnitRows")
        assert match, "expected to find mergeUnitRows function body in main.js"
        body = match.group(0)
        assert "not_running" in body, (
            "expected mergeUnitRows to flag synthesized rows with not_running"
        )

    @pytest.mark.unit
    def test_merge_unit_rows_derives_unit_stem_by_stripping_service_suffix(self):
        match = _extract_function_body(self.js, "mergeUnitRows")
        assert match, "expected to find mergeUnitRows function body in main.js"
        body = match.group(0)
        assert re.search(r"\.replace\(\s*/\\\.service\$/", body), (
            "expected mergeUnitRows to derive the unit stem by stripping a "
            "trailing .service suffix"
        )


class TestUpdateMonitoringViewCallsMergeUnitRows:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_update_monitoring_view_calls_merge_unit_rows(self):
        match = _extract_function_body(self.js, "updateMonitoringView")
        assert match, "expected to find updateMonitoringView function body in main.js"
        body = match.group(0)
        assert "mergeUnitRows" in body, (
            "expected updateMonitoringView to call mergeUnitRows"
        )


class TestMergeUnitRowsNameFallback:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_claims_a_unit_by_the_container_name_stem(self):
        match = _extract_function_body(self.js, "mergeUnitRows")
        assert match, "expected to find mergeUnitRows function body in main.js"
        body = match.group(0)
        assert re.search(r"\^systemd-", body), (
            "expected mergeUnitRows to strip a leading systemd- prefix from the "
            "container name when deriving the fallback claim"
        )
        assert re.search(r"['\"]\.service['\"]", body), (
            "expected mergeUnitRows to claim the unit built from the container "
            "name stem, so a container missing its PODMAN_SYSTEMD_UNIT label "
            "is not drawn twice"
        )


class TestRenderContainerRowUsesNotRunningFlag:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_render_container_row_references_not_running(self):
        match = _extract_function_body(self.js, "renderContainerRow")
        assert match, "expected to find renderContainerRow function body in main.js"
        body = match.group(0)
        assert "not_running" in body, (
            "expected renderContainerRow to reference not_running"
        )

    @pytest.mark.unit
    def test_render_container_row_uses_unit_badge_for_not_running_rows(self):
        match = _extract_function_body(self.js, "renderContainerRow")
        assert match, "expected to find renderContainerRow function body in main.js"
        body = match.group(0)
        assert "getUnitBadgeInfo" in body, (
            "expected renderContainerRow to call getUnitBadgeInfo so a "
            "not_running row's Status badge comes from the unit state rather "
            "than getHealthBadgeInfo"
        )
