"""Tests for extracting monitor time-series charts into ES module (charts.js).

These tests specify the migration for issue #432 where monitor chart creation,
swatch state management, and time-series configuration helpers move out of
main.js into:
  - static/modules/charts.js: chartSwatchIsOn, applySwatchState, chartColorFor,
    applyChartSelection, toggleChartSelection, refreshChartSwatches,
    _buildTimeSeriesConfig, initCpuChart, initMemChart, loadMonitorCharts
"""
import pathlib
import re

import pytest

from tests.js_source import read_static_js, static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

CHARTS_EXPORT_FUNCTIONS = [
    "chartSwatchIsOn",
    "applySwatchState",
    "chartColorFor",
    "applyChartSelection",
    "toggleChartSelection",
    "refreshChartSwatches",
    "_buildTimeSeriesConfig",
    "initCpuChart",
    "initMemChart",
    "loadMonitorCharts",
]

MOVED_FUNCTIONS = [
    "chartSwatchIsOn",
    "applySwatchState",
    "chartColorFor",
    "applyChartSelection",
    "toggleChartSelection",
    "refreshChartSwatches",
    "_buildTimeSeriesConfig",
    "initCpuChart",
    "initMemChart",
    "loadMonitorCharts",
]

MAIN_JS_CHARTS_IMPORTS = [
    "chartColorFor",
    "applySwatchState",
    "toggleChartSelection",
    "applyChartSelection",
    "refreshChartSwatches",
    "loadMonitorCharts",
    "initCpuChart",
    "initMemChart",
]

WINDOW_BRIDGE_CHARTS_NAMES = [
    "toggleChartSelection",
]


@pytest.mark.unit
def test_charts_module_exports_its_functions():
    """Assert static/modules/charts.js exists and exports all ten chart functions."""
    charts_js_path = REPO_ROOT / "static" / "modules" / "charts.js"
    assert charts_js_path.is_file(), (
        f"Expected charts module file to exist at {charts_js_path}; "
        "issue #432 extracts the monitor time-series charts into this module"
    )

    content = charts_js_path.read_text(encoding="utf-8")
    for name in CHARTS_EXPORT_FUNCTIONS:
        pattern = rf"\bexport\s+function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/charts.js must export function {name}; "
            "it is part of the extracted charts API"
        )


@pytest.mark.unit
def test_charts_module_declares_chart_global_for_eslint():
    """Assert static/modules/charts.js carries an eslint /* global ... */ comment naming Chart."""
    charts_js_path = REPO_ROOT / "static" / "modules" / "charts.js"
    assert charts_js_path.is_file(), (
        f"Expected charts module file to exist at {charts_js_path}; "
        "issue #432 extracts the monitor time-series charts into this module"
    )

    content = charts_js_path.read_text(encoding="utf-8")
    global_comment_match = re.search(r"/\*\s*global\b([^*]*)\*/", content)
    assert global_comment_match, (
        "static/modules/charts.js must include an eslint '/* global ... */' comment "
        "declaring globals provided outside the ES module graph"
    )
    globals_declared = {g.strip() for g in global_comment_match.group(1).split(",") if g.strip()}
    assert "Chart" in globals_declared or re.search(r"\bChart\b", global_comment_match.group(1)), (
        "static/modules/charts.js must declare 'Chart' in its /* global ... */ header "
        "so the CI eslint gate passes for the vendored chart.js bundle global"
    )


@pytest.mark.unit
def test_charts_module_imports_from_state_module():
    """Assert static/modules/charts.js imports state from @qm/state."""
    charts_js_path = REPO_ROOT / "static" / "modules" / "charts.js"
    assert charts_js_path.is_file(), (
        f"Expected charts module file to exist at {charts_js_path}; "
        "issue #432 extracts the monitor time-series charts into this module"
    )

    content = charts_js_path.read_text(encoding="utf-8")
    state_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/state['\"]", content)
    assert state_match, "static/modules/charts.js must import from the '@qm/state' bare specifier"

    imported = {n.strip() for n in state_match.group(1).split(",") if n.strip()}
    assert "state" in imported, (
        "static/modules/charts.js must import 'state' from @qm/state to access shared application state"
    )


@pytest.mark.unit
def test_charts_module_imports_from_theme_module():
    """Assert static/modules/charts.js imports getChartTheme from @qm/theme."""
    charts_js_path = REPO_ROOT / "static" / "modules" / "charts.js"
    assert charts_js_path.is_file(), (
        f"Expected charts module file to exist at {charts_js_path}; "
        "issue #432 extracts the monitor time-series charts into this module"
    )

    content = charts_js_path.read_text(encoding="utf-8")
    theme_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/theme['\"]", content)
    assert theme_match, "static/modules/charts.js must import from the '@qm/theme' bare specifier"

    imported = {n.strip() for n in theme_match.group(1).split(",") if n.strip()}
    assert "getChartTheme" in imported, (
        "static/modules/charts.js must import 'getChartTheme' from @qm/theme to style monitor charts according to active theme"
    )


@pytest.mark.unit
def test_charts_module_has_no_cyclic_or_main_imports():
    """Assert static/modules/charts.js contains no import from @qm/logs, @qm/terminal, or main.js."""
    charts_js_path = REPO_ROOT / "static" / "modules" / "charts.js"
    assert charts_js_path.is_file(), (
        f"Expected charts module file to exist at {charts_js_path}; "
        "issue #432 extracts the monitor time-series charts into this module"
    )

    content = charts_js_path.read_text(encoding="utf-8")
    assert not re.search(r"import\b.*from\s*['\"]@qm/logs['\"]", content), (
        "static/modules/charts.js must not import from @qm/logs to prevent cyclic dependencies"
    )
    assert not re.search(r"import\b.*from\s*['\"]@qm/terminal['\"]", content), (
        "static/modules/charts.js must not import from @qm/terminal to prevent cyclic dependencies"
    )
    assert not re.search(r"import\b.*from\s*['\"][^'\"]*main(?:\.js)?['\"]", content), (
        "static/modules/charts.js must not import from main.js to prevent cyclic dependencies"
    )


@pytest.mark.unit
def test_monitoring_chart_is_removed_from_all_static_js():
    """Assert monitoringChart is completely removed from all non-vendor static JS files."""
    static_js = read_static_js()
    assert "monitoringChart" not in static_js, (
        "monitoringChart was dead code (assigned nowhere in repository) "
        "and must be removed from all non-vendor static JS files rather than moved to charts.js"
    )


@pytest.mark.unit
def test_main_js_declares_none_of_the_moved_functions():
    """Assert main.js no longer declares any of the ten moved chart functions."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    for name in MOVED_FUNCTIONS:
        assert not re.search(rf"\bfunction\s+{re.escape(name)}\b", content), (
            f"main.js must not declare function {name}; it has moved to its dedicated ES module"
        )


@pytest.mark.unit
def test_main_js_imports_charts_functions_by_bare_specifier():
    """Assert main.js imports exactly the required chart names from @qm/charts."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    charts_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/charts['\"]", content)
    assert charts_match, "main.js must import from the '@qm/charts' bare specifier"

    imported_charts = {n.strip() for n in charts_match.group(1).split(",") if n.strip()}
    for name in MAIN_JS_CHARTS_IMPORTS:
        assert name in imported_charts, f"main.js must import {name} from @qm/charts"
    assert imported_charts == set(MAIN_JS_CHARTS_IMPORTS), (
        f"main.js must import exactly {MAIN_JS_CHARTS_IMPORTS} from @qm/charts with no unused imports"
    )


@pytest.mark.unit
def test_window_bridge_retains_chart_globals():
    """Assert toggleChartSelection remains in the window bridge."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    bridge_start = content.find("Object.assign(window, {")
    assert bridge_start != -1, "Object.assign(window, { block not found in main.js"

    bridge_end = content.find("});", bridge_start)
    assert bridge_end != -1, "End of Object.assign(window, { ... }); block not found in main.js"

    bridge_body = content[bridge_start:bridge_end]
    for name in WINDOW_BRIDGE_CHARTS_NAMES:
        assert name in bridge_body, (
            f"{name} must remain in the Object.assign(window, {{ ... }}) bridge; "
            "templates and e2e tests access it via window and would break without it"
        )
