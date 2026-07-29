"""Tests for Monitor pane accessibility (Issue #262).

Covers:
- templates/dashboard.html's monitor stat bar exposes its two
  `.monitor-stat-group` containers as `role="list"` and its six
  `.monitor-stat-block` children as `role="listitem"`, so the glance-bar
  counters read as a coherent list to assistive tech instead of a run of
  unrelated `<div>`s.
- templates/dashboard.html defines a `#monitor-health-status` live region
  that carries both `role="status"` and the existing `visually-hidden`
  class, so unhealthy-container changes can be announced without a
  visible element.
- static/main.js's stats-update logic (the function that maintains the
  `#mstat-unhealthy` glance-bar cell) gives an unhealthy count a
  non-colour indicator (an `aria-hidden` flag element with class
  `monitor-stat-flag`), not just a `classList.toggle('danger', ...)` CSS
  hook.
- static/main.js tracks the last-announced unhealthy count in a
  module-level `lastAnnouncedUnhealthy` variable and only rewrites
  `#monitor-health-status`'s text when the count actually changes,
  using announcement strings that mention "containers unhealthy" and
  "All containers healthy".
- static/main.js's `applyPercentSeverity` helper decorates a threshold
  cell with both an `aria-hidden` glyph (class `cell-flag`) and a
  `visually-hidden` word (`high` / `elevated`) describing the severity,
  instead of relying on colour (`cell-danger` / `cell-warn`) alone.
- static/main.js's `renderContainerRow` calls `applyPercentSeverity` for
  both the CPU and the MEM cell.
- static/main.js's `renderContainerStatsTable` gives every `<th>` a
  `scope="col"` attribute and adds a `visually-hidden` `<caption>` to the
  stats table, so screen-reader users get table semantics beyond the
  visual header row alone.
"""
import os
import re

import pytest

DASHBOARD_HTML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "dashboard.html"
)
JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "main.js")


def _dashboard_html():
    with open(DASHBOARD_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _js():
    with open(JS_PATH, encoding="utf-8") as f:
        return f.read()


# =============================================================================
# templates/dashboard.html: monitor stat bar list semantics
# =============================================================================


class TestMonitorStatBarListSemantics:
    def setup_method(self):
        self.html = _dashboard_html()

    def _stat_group_open_tags(self):
        return re.findall(
            r'<div\s+class\s*=\s*["\']monitor-stat-group(?:\s+monitor-stat-group-load)?["\'][^>]*>',
            self.html,
        )

    @pytest.mark.unit
    def test_stat_groups_are_lists(self):
        tags = self._stat_group_open_tags()
        assert len(tags) == 2, (
            "expected exactly two .monitor-stat-group opening tags in "
            f"dashboard.html, found {len(tags)}: {tags!r}"
        )
        for tag in tags:
            assert re.search(r'role\s*=\s*["\']list["\']', tag), (
                "expected every .monitor-stat-group div to carry "
                f'role="list", found: {tag!r}'
            )

    @pytest.mark.unit
    def test_stat_blocks_are_listitems(self):
        tags = re.findall(
            r'<div\s+class\s*=\s*["\']monitor-stat-block["\'][^>]*>', self.html
        )
        assert len(tags) == 6, (
            "expected exactly six .monitor-stat-block opening tags in "
            f"dashboard.html, found {len(tags)}: {tags!r}"
        )
        for tag in tags:
            assert re.search(r'role\s*=\s*["\']listitem["\']', tag), (
                "expected every .monitor-stat-block div to carry "
                f'role="listitem", found: {tag!r}'
            )


# =============================================================================
# templates/dashboard.html: #monitor-health-status live region
# =============================================================================


class TestMonitorHealthStatusRegion:
    def setup_method(self):
        self.html = _dashboard_html()

    @pytest.mark.unit
    def test_health_status_region_exists(self):
        match = re.search(
            r'<[a-zA-Z0-9]+[^>]*\bid\s*=\s*["\']monitor-health-status["\'][^>]*>',
            self.html,
        )
        assert match, (
            "expected to find an element with id=\"monitor-health-status\" "
            "in dashboard.html"
        )
        tag = match.group(0)
        assert re.search(r'role\s*=\s*["\']status["\']', tag), (
            'expected #monitor-health-status to carry role="status", '
            f"found: {tag!r}"
        )
        assert re.search(r'class\s*=\s*["\'][^"\']*\bvisually-hidden\b[^"\']*["\']', tag), (
            "expected #monitor-health-status to carry the visually-hidden "
            f"class, found: {tag!r}"
        )


# =============================================================================
# static/main.js: unhealthy-count non-colour indicator + announcement
# =============================================================================


class TestMainJsUnhealthyIndicatorAndAnnouncement:
    def setup_method(self):
        self.js = _js()

    def _stats_update_region(self):
        # The function that maintains #mstat-unhealthy (currently named
        # updateStats; tolerate a rename to updateMonitorStats by locating
        # it via the unique mstat-unhealthy marker rather than a hardcoded
        # function name).
        marker = "getElementById('mstat-unhealthy')"
        start = self.js.find(marker)
        assert start != -1, (
            "expected to locate the code that reads #mstat-unhealthy in "
            "main.js"
        )
        # Walk backwards to the start of the enclosing function.
        fn_start = self.js.rfind("function ", 0, start)
        assert fn_start != -1, (
            "expected the #mstat-unhealthy code to live inside a "
            "top-level function in main.js"
        )
        # Walk forwards to the next top-level function declaration to
        # bound the region.
        next_fn = self.js.find("\nfunction ", start)
        end = next_fn if next_fn != -1 else len(self.js)
        return self.js[fn_start:end]

    @pytest.mark.unit
    def test_unhealthy_count_has_non_colour_indicator(self):
        region = self._stats_update_region()
        assert "classList.toggle('danger'" in region or 'classList.toggle("danger"' in region, (
            "sanity check: expected the unhealthy branch to still toggle "
            f"the 'danger' class, region: {region!r}"
        )
        assert re.search(r"aria-hidden", region), (
            "expected the unhealthy branch to append a child element "
            f"carrying aria-hidden, region: {region!r}"
        )
        assert re.search(r"monitor-stat-flag", region), (
            "expected the unhealthy branch to append a child element with "
            f"class monitor-stat-flag, region: {region!r}"
        )
        assert re.search(r"unhealthy\s*>\s*0", region), (
            "expected the flag element to only be appended when "
            f"unhealthy > 0, region: {region!r}"
        )

    @pytest.mark.unit
    def test_unhealthy_announced_only_on_change(self):
        assert re.search(
            r"\b(?:let|var)\s+lastAnnouncedUnhealthy\b", self.js
        ), (
            "expected a module-level `lastAnnouncedUnhealthy` tracker "
            "declared in main.js"
        )

        region = self._stats_update_region()
        assert "lastAnnouncedUnhealthy" in region, (
            "expected the stats-update function to reference "
            f"lastAnnouncedUnhealthy, region: {region!r}"
        )
        assert re.search(
            r"unhealthy\s*(?:!==|!=)\s*lastAnnouncedUnhealthy"
            r"|lastAnnouncedUnhealthy\s*(?:!==|!=)\s*unhealthy",
            region,
        ), (
            "expected a comparison of the new unhealthy count against "
            f"lastAnnouncedUnhealthy to guard the announcement, region: {region!r}"
        )
        assert re.search(r"monitor-health-status", region), (
            "expected the stats-update function to write to "
            f"#monitor-health-status, region: {region!r}"
        )
        assert "containers unhealthy" in region, (
            "expected an announcement string mentioning 'containers "
            f"unhealthy', region: {region!r}"
        )
        assert "All containers healthy" in region, (
            "expected an announcement string 'All containers healthy', "
            f"region: {region!r}"
        )


# =============================================================================
# static/main.js: applyPercentSeverity helper
# =============================================================================


class TestApplyPercentSeverityHelper:
    def setup_method(self):
        self.js = _js()

    def _helper_region(self):
        start = self.js.find("function applyPercentSeverity")
        assert start != -1, (
            "expected a function named applyPercentSeverity in main.js"
        )
        next_fn = self.js.find("\nfunction ", start)
        end = next_fn if next_fn != -1 else len(self.js)
        return self.js[start:end]

    @pytest.mark.unit
    def test_threshold_cells_have_glyph_and_hidden_word(self):
        region = self._helper_region()
        assert re.search(r"aria-hidden", region), (
            "expected applyPercentSeverity to append an aria-hidden glyph "
            f"element, region: {region!r}"
        )
        assert re.search(r"cell-flag", region), (
            "expected applyPercentSeverity to append an element with "
            f"class cell-flag, region: {region!r}"
        )
        assert re.search(r"visually-hidden", region), (
            "expected applyPercentSeverity to append a visually-hidden "
            f"span, region: {region!r}"
        )
        assert re.search(r"\bhigh\b", region), (
            "expected applyPercentSeverity to use the severity word "
            f"'high', region: {region!r}"
        )
        assert re.search(r"\belevated\b", region), (
            "expected applyPercentSeverity to use the severity word "
            f"'elevated', region: {region!r}"
        )

    @pytest.mark.unit
    def test_threshold_cells_use_the_helper(self):
        start = self.js.find("function renderContainerRow")
        assert start != -1, (
            "expected a function named renderContainerRow in main.js"
        )
        next_fn = self.js.find("\nfunction ", start)
        end = next_fn if next_fn != -1 else len(self.js)
        region = self.js[start:end]

        calls = re.findall(r"applyPercentSeverity\s*\(", region)
        assert len(calls) >= 2, (
            "expected renderContainerRow to call applyPercentSeverity for "
            f"both the CPU and the MEM cell, found {len(calls)} call(s) "
            f"in region: {region!r}"
        )


# =============================================================================
# static/main.js: renderContainerStatsTable scope + caption
# =============================================================================


class TestRenderContainerStatsTableSemantics:
    def setup_method(self):
        self.js = _js()

    def _render_region(self):
        start = self.js.find("function renderContainerStatsTable")
        assert start != -1, (
            "expected a function named renderContainerStatsTable in "
            "main.js"
        )
        next_fn = self.js.find("\nfunction ", start)
        end = next_fn if next_fn != -1 else len(self.js)
        return self.js[start:end]

    @pytest.mark.unit
    def test_stats_table_headers_have_scope(self):
        region = self._render_region()
        assert re.search(
            r"th\.scope\s*=\s*['\"]col['\"]"
            r"|th\.setAttribute\(\s*['\"]scope['\"]\s*,\s*['\"]col['\"]\s*\)",
            region,
        ), (
            "expected renderContainerStatsTable's th construction to set "
            f"scope to 'col', region: {region!r}"
        )

    @pytest.mark.unit
    def test_stats_table_has_caption(self):
        region = self._render_region()
        assert re.search(
            r"createElement\(\s*['\"]caption['\"]\s*\)", region
        ), (
            "expected renderContainerStatsTable to create a caption "
            f"element, region: {region!r}"
        )
        assert re.search(r"visually-hidden", region), (
            "expected the caption element to carry the visually-hidden "
            f"class, region: {region!r}"
        )
