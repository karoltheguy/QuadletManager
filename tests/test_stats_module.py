"""Tests for extracting container stats table, fleet counts, and monitor summary strip into ES module (stats.js).

These tests specify the migration for issue #437 where container stats table rendering,
unit indexing/merging, fleet counts computation, and the monitor summary strip move out of
main.js into:
  - static/modules/stats.js: parsePercent, getPercentClass, getHealthBadgeInfo,
    buildUnitIndex, getUnitBadgeInfo, mergeUnitRows, applyPercentSeverity,
    getStatusBadgeInfo, renderContainerRow, renderContainerStatsTable,
    updateFilterCount, computeServerTotals, computeUnitCounts, renderUnhealthyStat,
    renderFailedStat, healthAnnouncement, announceHealthChange, updateSummaryStrip
"""
import pathlib
import re

import pytest

from tests.js_source import static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

STATS_EXPORT_FUNCTIONS = [
    "parsePercent",
    "getPercentClass",
    "getHealthBadgeInfo",
    "buildUnitIndex",
    "getUnitBadgeInfo",
    "mergeUnitRows",
    "applyPercentSeverity",
    "getStatusBadgeInfo",
    "renderContainerRow",
    "renderContainerStatsTable",
    "updateFilterCount",
    "computeServerTotals",
    "computeUnitCounts",
    "renderUnhealthyStat",
    "renderFailedStat",
    "healthAnnouncement",
    "announceHealthChange",
    "updateSummaryStrip",
]

MAIN_JS_STATS_IMPORTS = [
    "parsePercent",
    "mergeUnitRows",
    "renderContainerStatsTable",
    "updateSummaryStrip",
    "updateFilterCount",
]

MONITOR_PANE_RETAINED_FUNCTIONS = [
    "applyContainerFilter",
    "applyMonitorFilter",
    "updateMonitoringView",
]


@pytest.mark.unit
def test_stats_module_exports_its_functions():
    """Assert static/modules/stats.js exists and exports all 18 stats functions."""
    stats_js_path = REPO_ROOT / "static" / "modules" / "stats.js"
    assert stats_js_path.is_file(), (
        f"Expected stats module file to exist at {stats_js_path}; "
        "issue #437 extracts the container stats table, fleet counts and monitor summary strip into this module"
    )

    content = stats_js_path.read_text(encoding="utf-8")
    for name in STATS_EXPORT_FUNCTIONS:
        pattern = rf"\bexport\s+function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/stats.js must export function {name}; "
            "it is part of the extracted stats API for issue #437"
        )


@pytest.mark.unit
def test_stats_module_owns_the_shared_values():
    """Assert static/modules/stats.js declares STAT_PLACEHOLDER and lastAnnouncedUnhealthy."""
    stats_js_path = REPO_ROOT / "static" / "modules" / "stats.js"
    assert stats_js_path.is_file(), (
        f"Expected stats module file to exist at {stats_js_path}; "
        "issue #437 extracts the container stats table, fleet counts and monitor summary strip into this module"
    )

    content = stats_js_path.read_text(encoding="utf-8")
    assert "STAT_PLACEHOLDER" in content, (
        "static/modules/stats.js must declare STAT_PLACEHOLDER; "
        "issue #437 moves this shared value into the stats module"
    )
    assert "lastAnnouncedUnhealthy" in content, (
        "static/modules/stats.js must declare lastAnnouncedUnhealthy; "
        "issue #437 moves this shared value into the stats module"
    )


@pytest.mark.unit
def test_stats_module_imports_from_state_and_dom():
    """Assert static/modules/stats.js imports state from @qm/state and setStatText from @qm/dom."""
    stats_js_path = REPO_ROOT / "static" / "modules" / "stats.js"
    assert stats_js_path.is_file(), (
        f"Expected stats module file to exist at {stats_js_path}; "
        "issue #437 extracts the container stats table, fleet counts and monitor summary strip into this module"
    )

    content = stats_js_path.read_text(encoding="utf-8")
    state_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/state['\"]", content)
    assert state_match, (
        "static/modules/stats.js must import from the '@qm/state' bare specifier; issue #437"
    )
    imported_state = {n.strip() for n in state_match.group(1).split(",") if n.strip()}
    assert "state" in imported_state, (
        "static/modules/stats.js must import 'state' from @qm/state to access shared application state; issue #437"
    )

    dom_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/dom['\"]", content)
    assert dom_match, (
        "static/modules/stats.js must import from the '@qm/dom' bare specifier; issue #437"
    )
    imported_dom = {n.strip() for n in dom_match.group(1).split(",") if n.strip()}
    assert "setStatText" in imported_dom, (
        "static/modules/stats.js must import 'setStatText' from @qm/dom to update summary strip elements; issue #437"
    )


@pytest.mark.unit
def test_stats_module_imports_from_charts():
    """Assert static/modules/stats.js imports chartColorFor, applySwatchState, and toggleChartSelection from @qm/charts."""
    stats_js_path = REPO_ROOT / "static" / "modules" / "stats.js"
    assert stats_js_path.is_file(), (
        f"Expected stats module file to exist at {stats_js_path}; "
        "issue #437 extracts the container stats table, fleet counts and monitor summary strip into this module"
    )

    content = stats_js_path.read_text(encoding="utf-8")
    charts_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/charts['\"]", content)
    assert charts_match, (
        "static/modules/stats.js must import from the '@qm/charts' bare specifier; issue #437"
    )
    imported_charts = {n.strip() for n in charts_match.group(1).split(",") if n.strip()}
    for name in ["chartColorFor", "applySwatchState", "toggleChartSelection"]:
        assert name in imported_charts, (
            f"static/modules/stats.js must import '{name}' from @qm/charts; issue #437"
        )


@pytest.mark.unit
def test_stats_module_has_no_cyclic_or_main_imports():
    """Assert static/modules/stats.js contains no import of main.js and no self-import from @qm/stats."""
    stats_js_path = REPO_ROOT / "static" / "modules" / "stats.js"
    assert stats_js_path.is_file(), (
        f"Expected stats module file to exist at {stats_js_path}; "
        "issue #437 extracts the container stats table, fleet counts and monitor summary strip into this module"
    )

    content = stats_js_path.read_text(encoding="utf-8")
    assert not re.search(r"import\b.*from\s*['\"][^'\"]*main(?:\.js)?['\"]", content), (
        "static/modules/stats.js must not import from main.js to prevent cyclic dependencies; issue #437"
    )
    assert not re.search(r"import\b.*from\s*['\"]@qm/stats['\"]", content), (
        "static/modules/stats.js must not import from itself (@qm/stats); issue #437"
    )


@pytest.mark.unit
def test_main_js_no_longer_declares_the_stats_functions():
    """Assert static/main.js no longer declares any of the 18 moved stats functions, STAT_PLACEHOLDER, or lastAnnouncedUnhealthy."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    for name in STATS_EXPORT_FUNCTIONS:
        assert not re.search(rf"\bfunction\s+{re.escape(name)}\b", content), (
            f"main.js must not declare function {name}; it has moved to static/modules/stats.js for issue #437"
        )
    assert not re.search(r"\bconst\s+STAT_PLACEHOLDER\b", content), (
        "main.js must not declare STAT_PLACEHOLDER; it has moved to static/modules/stats.js for issue #437"
    )
    assert not re.search(r"\blet\s+lastAnnouncedUnhealthy\b", content), (
        "main.js must not declare lastAnnouncedUnhealthy; it has moved to static/modules/stats.js for issue #437"
    )


@pytest.mark.unit
def test_main_js_imports_the_stats_module():
    """Assert static/main.js imports the 6 required stats functions from @qm/stats."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    stats_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/stats['\"]", content)
    assert stats_match, (
        "main.js must import from the '@qm/stats' bare specifier; issue #437"
    )

    imported_stats = {n.strip() for n in stats_match.group(1).split(",") if n.strip()}
    for name in MAIN_JS_STATS_IMPORTS:
        assert name in imported_stats, (
            f"main.js must import {name} from @qm/stats; issue #437"
        )
    assert imported_stats == set(MAIN_JS_STATS_IMPORTS), (
        f"main.js must import exactly {MAIN_JS_STATS_IMPORTS} from @qm/stats with no unused imports; issue #437"
    )


@pytest.mark.unit
def test_monitor_pane_functions_stay_in_main_js():
    """Assert static/main.js still declares applyContainerFilter, applyMonitorFilter, and updateMonitoringView."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    for name in MONITOR_PANE_RETAINED_FUNCTIONS:
        assert re.search(rf"\bfunction\s+{re.escape(name)}\b", content), (
            f"main.js must still declare function {name}; "
            "it stays in main.js to prevent circular imports for issue #437"
        )


@pytest.mark.unit
def test_render_container_stats_table_stays_on_the_window_bridge():
    """Assert renderContainerStatsTable remains in the Object.assign(window, { ... }) bridge in main.js."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    bridge_start = content.find("Object.assign(window, {")
    assert bridge_start != -1, "Object.assign(window, { block not found in main.js; issue #437"

    bridge_end = content.find("});", bridge_start)
    assert bridge_end != -1, "End of Object.assign(window, { ... }); block not found in main.js; issue #437"

    bridge_body = content[bridge_start:bridge_end]
    assert "renderContainerStatsTable" in bridge_body, (
        "renderContainerStatsTable must remain in the Object.assign(window, { ... }) bridge; "
        "templates and external consumers access it via window; issue #437"
    )
