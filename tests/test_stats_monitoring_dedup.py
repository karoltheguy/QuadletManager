import pytest
"""
Tests for deduplication of stats/monitoring chart and table rendering logic.
These are structural tests — they verify that shared factory helpers exist in
main.js and that the duplicated inline logic has been extracted into them.
No running backend is required.
"""
import re

from tests.css_source import read_static_css
from tests.js_source import read_static_js


def _src():
    return read_static_js()


# ── Chart factory ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_monitor_time_series_charts_use_factory():
    """initCpuChart and initMemChart must delegate to _buildTimeSeriesConfig (#88)."""
    src = _src()
    cpu_m = re.search(r'function\s+initCpuChart\s*\(\)(.*?)(?=\nfunction\s|\Z)', src, re.DOTALL)
    assert cpu_m, "initCpuChart not found — time-series charts should replace the old bar chart"
    assert '_buildTimeSeriesConfig' in cpu_m.group(1), "initCpuChart must call _buildTimeSeriesConfig"

    mem_m = re.search(r'function\s+initMemChart\s*\(\)(.*?)(?=\nfunction\s|\Z)', src, re.DOTALL)
    assert mem_m, "initMemChart not found"
    assert '_buildTimeSeriesConfig' in mem_m.group(1), "initMemChart must call _buildTimeSeriesConfig"


# ── Table renderer ───────────────────────────────────────────────────────────

@pytest.mark.unit
def test_render_container_stats_table_exists():
    """A shared renderContainerStatsTable(tableElId, data) helper must exist."""
    assert re.search(r'function\s+renderContainerStatsTable\s*\(', _src()), (
        "renderContainerStatsTable helper function not found in main.js"
    )


@pytest.mark.unit
def test_update_monitoring_view_uses_shared_table_renderer():
    """updateMonitoringView must delegate table rendering to renderContainerStatsTable."""
    src = _src()
    m = re.search(r'function\s+updateMonitoringView\s*\(data\)(.*?)(?=\nfunction |\nexport function |\nwindow\.|\Z)', src, re.DOTALL)
    assert m, "updateMonitoringView not found"
    body = m.group(1)
    assert 'renderContainerStatsTable' in body, (
        "updateMonitoringView must call renderContainerStatsTable"
    )
    assert '<table class=' not in body, (
        "updateMonitoringView must not contain inline table HTML"
    )


# ── Dead #stats-table removal ────────────────────────────────────────────────

@pytest.mark.unit
def test_dead_stats_table_paths_removed():
    """The dead #stats-table element and its chart/update paths must be gone from main.js."""
    src = _src()
    assert not re.search(r'\bstatsChart\b', src), (
        "statsChart identifier still present in main.js — dead chart code not removed"
    )
    assert not re.search(r'\bupdateStats\b', src), (
        "updateStats identifier still present in main.js — dead update path not removed"
    )
    assert not re.search(r'\binitStatsChart\b', src), (
        "initStatsChart identifier still present in main.js — dead chart init not removed"
    )
    assert not re.search(r'\bbuildBarChartConfig\b', src), (
        "buildBarChartConfig identifier still present in main.js — dead chart config factory not removed"
    )
    assert not re.search(r'(?<!monitoring-)stats-table(?!-wrapper)', src), (
        "stats-table element id still present in main.js — dead #stats-table references not removed"
    )


@pytest.mark.unit
def test_dead_stats_table_css_removed():
    """The dead #stats-table selector must be gone from style.css."""
    css = read_static_css()
    assert not re.search(r'(?<!monitoring-)#stats-table', css), (
        "#stats-table selector still present in style.css — dead styling not removed"
    )
