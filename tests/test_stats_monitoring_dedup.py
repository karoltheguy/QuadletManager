"""
Tests for deduplication of stats/monitoring chart and table rendering logic.
These are structural tests — they verify that shared factory helpers exist in
main.js and that the duplicated inline logic has been extracted into them.
No running backend is required.
"""
import re
import pathlib

MAIN_JS = pathlib.Path(__file__).parent.parent / "static" / "main.js"


def _src():
    return MAIN_JS.read_text()


# ── Chart factory ────────────────────────────────────────────────────────────

def test_build_bar_chart_config_factory_exists():
    """A shared buildBarChartConfig(elementId) factory function must exist."""
    assert re.search(r'function\s+buildBarChartConfig\s*\(', _src()), (
        "buildBarChartConfig factory function not found in main.js"
    )


def test_init_stats_chart_uses_factory():
    """initStatsChart must delegate to buildBarChartConfig, not inline the config."""
    src = _src()
    # Find the body of initStatsChart
    m = re.search(r'function\s+initStatsChart\s*\(\)(.*?)(?=\nfunction\s|\Z)', src, re.DOTALL)
    assert m, "initStatsChart not found"
    body = m.group(1)
    assert 'buildBarChartConfig' in body, "initStatsChart must call buildBarChartConfig"
    # Must NOT contain the full duplicated dataset inline config
    assert "backgroundColor: 'rgba(99, 102, 241" not in body, (
        "initStatsChart still contains inline dataset config — extract into buildBarChartConfig"
    )


def test_init_monitoring_chart_uses_factory():
    """initMonitoringChart must delegate to buildBarChartConfig, not inline the config."""
    src = _src()
    m = re.search(r'function\s+initMonitoringChart\s*\(\)(.*?)(?=\nfunction\s|\Z)', src, re.DOTALL)
    assert m, "initMonitoringChart not found"
    body = m.group(1)
    assert 'buildBarChartConfig' in body, "initMonitoringChart must call buildBarChartConfig"
    assert "backgroundColor: 'rgba(99, 102, 241" not in body, (
        "initMonitoringChart still contains inline dataset config — extract into buildBarChartConfig"
    )


# ── Table renderer ───────────────────────────────────────────────────────────

def test_render_container_stats_table_exists():
    """A shared renderContainerStatsTable(tableElId, data) helper must exist."""
    assert re.search(r'function\s+renderContainerStatsTable\s*\(', _src()), (
        "renderContainerStatsTable helper function not found in main.js"
    )


def test_update_stats_uses_shared_table_renderer():
    """updateStats must delegate table rendering to renderContainerStatsTable."""
    src = _src()
    m = re.search(r'function\s+updateStats\s*\(data\)(.*?)(?=\n\nfunction\s|\Z)', src, re.DOTALL)
    assert m, "updateStats not found"
    body = m.group(1)
    assert 'renderContainerStatsTable' in body, (
        "updateStats must call renderContainerStatsTable"
    )
    assert '<table class=' not in body, (
        "updateStats still contains inline table HTML — extract into renderContainerStatsTable"
    )


def test_update_monitoring_view_uses_shared_table_renderer():
    """updateMonitoringView must delegate table rendering to renderContainerStatsTable."""
    src = _src()
    m = re.search(r'function\s+updateMonitoringView\s*\(data\)(.*?)(?=\n\nfunction\s|\Z)', src, re.DOTALL)
    assert m, "updateMonitoringView not found"
    body = m.group(1)
    assert 'renderContainerStatsTable' in body, (
        "updateMonitoringView must call renderContainerStatsTable"
    )
    assert '<table class=' not in body, (
        "updateMonitoringView still contains inline table HTML — extract into renderContainerStatsTable"
    )
