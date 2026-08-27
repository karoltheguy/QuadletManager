"""Tests for extracting Monitor pane into ES module (monitor.js).

These tests specify the migration for issue #439 where the Monitor pane functions
move out of main.js into:
  - static/modules/monitor.js: showMonitoringEmptyState,
    renderMonitoringServerStats, restoreMonitoringServerSelection,
    selectMonitoringServer, applyMonitorFilter, updateMonitoringView,
    applyContainerFilter, handleMonitorTabActivation,
    refreshMonitoringServerDropdown
"""
import pathlib
import re

import pytest

from tests.js_source import static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

MONITOR_EXPORT_FUNCTIONS = [
    "showMonitoringEmptyState",
    "renderMonitoringServerStats",
    "restoreMonitoringServerSelection",
    "selectMonitoringServer",
    "applyMonitorFilter",
    "updateMonitoringView",
    "applyContainerFilter",
    "handleMonitorTabActivation",
    "refreshMonitoringServerDropdown",
]

MAIN_JS_MONITOR_IMPORTS = [
    "updateMonitoringView",
    "selectMonitoringServer",
    "applyContainerFilter",
    "restoreMonitoringServerSelection",
    "handleMonitorTabActivation",
]


@pytest.mark.unit
def test_monitor_module_exports_its_functions():
    """Assert static/modules/monitor.js exists and exports all nine monitor functions."""
    monitor_js_path = REPO_ROOT / "static" / "modules" / "monitor.js"
    assert monitor_js_path.is_file(), (
        f"Expected monitor module file to exist at {monitor_js_path}; "
        "issue #439 extracts the Monitor pane into this module"
    )

    content = monitor_js_path.read_text(encoding="utf-8")
    for name in MONITOR_EXPORT_FUNCTIONS:
        pattern = rf"\bexport\s+function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/monitor.js must export function {name}; "
            "it is part of the extracted monitor API for issue #439"
        )


@pytest.mark.unit
def test_main_js_no_longer_declares_the_monitor_functions():
    """Assert static/main.js no longer declares any of the nine moved monitor functions."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    for name in MONITOR_EXPORT_FUNCTIONS:
        assert not re.search(rf"\bfunction\s+{re.escape(name)}\b", content), (
            f"main.js must not declare function {name}; "
            "it has moved to static/modules/monitor.js for issue #439"
        )


@pytest.mark.unit
def test_main_js_imports_the_monitor_module():
    """Assert static/main.js imports the required monitor functions from @qm/monitor."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    monitor_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/monitor['\"]", content)
    assert monitor_match, (
        "main.js must import from the '@qm/monitor' bare specifier; issue #439"
    )

    imported_monitor = {n.strip() for n in monitor_match.group(1).split(",") if n.strip()}
    for name in MAIN_JS_MONITOR_IMPORTS:
        assert name in imported_monitor, (
            f"main.js must import {name} from @qm/monitor; issue #439"
        )
