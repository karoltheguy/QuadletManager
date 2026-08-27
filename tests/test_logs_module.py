"""Tests for extracting log-tailing client and unit helpers into ES modules (logs.js, units.js).

These tests specify the migration for issue #428 where log streaming functions,
log tab management, and quadlet unit helpers move out of main.js into:
  - static/modules/logs.js: showLogMessage, tailLogsFromPanel, createLogTab,
    openLogSocket, switchLogTab, handleClosedLogTabFallback, closeLogTab, initLogs
  - static/modules/units.js: unitNameFor, stemFromUnitName, SUFFIXED_QUADLET_TYPES
  - static/modules/panel.js: refreshSessionsStripVisibility
"""
import pathlib
import re

import pytest

from tests.js_source import static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

LOGS_EXPORT_FUNCTIONS = [
    "showLogMessage",
    "tailLogsFromPanel",
    "createLogTab",
    "openLogSocket",
    "switchLogTab",
    "handleClosedLogTabFallback",
    "closeLogTab",
    "initLogs",
]

UNITS_EXPORT_FUNCTIONS = [
    "unitNameFor",
    "stemFromUnitName",
]

MOVED_FUNCTIONS = [
    "showLogMessage",
    "tailLogsFromPanel",
    "createLogTab",
    "openLogSocket",
    "switchLogTab",
    "handleClosedLogTabFallback",
    "closeLogTab",
    "unitNameFor",
    "stemFromUnitName",
    "refreshSessionsStripVisibility",
]


@pytest.mark.unit
def test_logs_module_exports_its_functions():
    """Assert static/modules/logs.js exists and exports all eight log functions."""
    logs_js_path = REPO_ROOT / "static" / "modules" / "logs.js"
    assert logs_js_path.is_file(), (
        f"Expected logs module file to exist at {logs_js_path}; "
        "issue #428 extracts the /ws/logs client into this module"
    )

    content = logs_js_path.read_text(encoding="utf-8")
    for name in LOGS_EXPORT_FUNCTIONS:
        pattern = rf"\bexport\s+function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/logs.js must export function {name}; "
            "it is part of the extracted logs client API"
        )


@pytest.mark.unit
def test_init_logs_owns_the_change_listener():
    """Assert the #log-since-select change listener registers inside initLogs.

    Importing a module must have no side effects, so the change event listener
    on #log-since-select must register inside the exported initLogs function
    rather than at module top level.
    """
    logs_js_path = REPO_ROOT / "static" / "modules" / "logs.js"
    assert logs_js_path.is_file(), (
        f"Expected logs module file to exist at {logs_js_path}; "
        "issue #428 extracts the /ws/logs client into this module"
    )

    content = logs_js_path.read_text(encoding="utf-8")
    init_match = re.search(r"\bexport\s+function\s+initLogs\b", content)
    assert init_match, "static/modules/logs.js must export function initLogs"

    listener_match = re.search(r"addEventListener\(\s*['\"]change['\"]", content)
    assert listener_match, (
        "static/modules/logs.js must register an event listener for 'change'"
    )
    assert listener_match.start() > init_match.start(), (
        "the 'change' listener must register inside initLogs, not at module "
        "top level, so importing static/modules/logs.js has no side effects"
    )


@pytest.mark.unit
def test_logs_module_imports_from_state_module():
    """Assert static/modules/logs.js imports state, lastStatsPerServer, and _logTabs from @qm/state."""
    logs_js_path = REPO_ROOT / "static" / "modules" / "logs.js"
    assert logs_js_path.is_file(), (
        f"Expected logs module file to exist at {logs_js_path}; "
        "issue #428 extracts the /ws/logs client into this module"
    )

    content = logs_js_path.read_text(encoding="utf-8")
    state_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/state['\"]", content)
    assert state_match, "static/modules/logs.js must import from the '@qm/state' bare specifier"

    imported = {n.strip() for n in state_match.group(1).split(",") if n.strip()}
    for name in ["state", "lastStatsPerServer", "_logTabs"]:
        assert name in imported, (
            f"static/modules/logs.js must import '{name}' from @qm/state to access shared application state"
        )


@pytest.mark.unit
def test_logs_module_imports_from_panel_module():
    """Assert static/modules/logs.js imports openBottomPanel, switchBottomTab, and refreshSessionsStripVisibility from @qm/panel."""
    logs_js_path = REPO_ROOT / "static" / "modules" / "logs.js"
    assert logs_js_path.is_file(), (
        f"Expected logs module file to exist at {logs_js_path}; "
        "issue #428 extracts the /ws/logs client into this module"
    )

    content = logs_js_path.read_text(encoding="utf-8")
    panel_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/panel['\"]", content)
    assert panel_match, "static/modules/logs.js must import from the '@qm/panel' bare specifier"

    imported = {n.strip() for n in panel_match.group(1).split(",") if n.strip()}
    for name in ["openBottomPanel", "switchBottomTab", "refreshSessionsStripVisibility"]:
        assert name in imported, (
            f"static/modules/logs.js must import '{name}' from @qm/panel to manage bottom panel and tab visibility"
        )


@pytest.mark.unit
def test_logs_module_imports_from_units_module():
    """Assert static/modules/logs.js imports unitNameFor from @qm/units."""
    logs_js_path = REPO_ROOT / "static" / "modules" / "logs.js"
    assert logs_js_path.is_file(), (
        f"Expected logs module file to exist at {logs_js_path}; "
        "issue #428 extracts the /ws/logs client into this module"
    )

    content = logs_js_path.read_text(encoding="utf-8")
    units_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/units['\"]", content)
    assert units_match, "static/modules/logs.js must import from the '@qm/units' bare specifier"

    imported = {n.strip() for n in units_match.group(1).split(",") if n.strip()}
    assert "unitNameFor" in imported, (
        "static/modules/logs.js must import 'unitNameFor' from @qm/units to compute Quadlet service unit names"
    )


@pytest.mark.unit
def test_units_module_exports_its_functions_and_constants():
    """Assert static/modules/units.js exists, exports unitNameFor and stemFromUnitName, and contains SUFFIXED_QUADLET_TYPES."""
    units_js_path = REPO_ROOT / "static" / "modules" / "units.js"
    assert units_js_path.is_file(), (
        f"Expected units module file to exist at {units_js_path}; "
        "issue #428 extracts Quadlet unit-naming helpers into this module"
    )

    content = units_js_path.read_text(encoding="utf-8")
    for name in UNITS_EXPORT_FUNCTIONS:
        pattern = rf"\bexport\s+function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/units.js must export function {name}"
        )
    assert "SUFFIXED_QUADLET_TYPES" in content, (
        "static/modules/units.js must contain 'SUFFIXED_QUADLET_TYPES' to identify suffixed Quadlet types"
    )


@pytest.mark.unit
def test_panel_module_exports_refresh_sessions_strip_visibility():
    """Assert static/modules/panel.js exports refreshSessionsStripVisibility."""
    panel_js_path = REPO_ROOT / "static" / "modules" / "panel.js"
    assert panel_js_path.is_file(), f"Expected panel module file to exist at {panel_js_path}"

    content = panel_js_path.read_text(encoding="utf-8")
    pattern = r"\bexport\s+function\s+refreshSessionsStripVisibility\b"
    assert re.search(pattern, content), (
        "static/modules/panel.js must export function refreshSessionsStripVisibility "
        "because both terminal and log chip clusters share the session tabs strip"
    )


@pytest.mark.unit
def test_main_js_declares_none_of_the_moved_functions():
    """Assert main.js no longer declares any of the eleven moved log, unit, or panel functions."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    for name in MOVED_FUNCTIONS:
        assert not re.search(rf"\bfunction\s+{re.escape(name)}\b", content), (
            f"main.js must not declare function {name}; it has moved to its dedicated ES module"
        )
    assert not re.search(r"\bconst\s+setupLogSinceSelector\b", content), (
        "main.js must not declare setupLogSinceSelector; listener registration moved to initLogs in static/modules/logs.js"
    )


@pytest.mark.unit
def test_main_js_imports_moved_functions_by_bare_specifier():
    """Assert main.js imports every moved name it still calls from @qm/logs, @qm/units, and @qm/panel."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")

    # 1. Imports from @qm/logs
    logs_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/logs['\"]", content)
    assert logs_match, "main.js must import from the '@qm/logs' bare specifier"
    imported_logs = {n.strip() for n in logs_match.group(1).split(",") if n.strip()}
    for name in [
        "tailLogsFromPanel",
        "createLogTab",
        "switchLogTab",
        "closeLogTab",
        "initLogs",
    ]:
        assert name in imported_logs, f"main.js must import {name} from @qm/logs"

    # 2. Imports from @qm/units
    units_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/units['\"]", content)
    assert units_match, "main.js must import from the '@qm/units' bare specifier"
    imported_units = {n.strip() for n in units_match.group(1).split(",") if n.strip()}
    for name in ["unitNameFor", "stemFromUnitName"]:
        assert name in imported_units, f"main.js must import {name} from @qm/units"

    # main.js no longer imports refreshSessionsStripVisibility itself. #428 needed
    # it because handleClosedTabFallback still lived here; #430 moved that into
    # terminal.js, which imports the helper directly. The rule this assertion was
    # protecting -- that the helper lives in panel.js rather than main.js, so
    # logs.js and terminal.js can reach it without importing main.js -- is covered
    # by test_panel_module_exports_refresh_sessions_strip_visibility above.


@pytest.mark.unit
def test_main_js_calls_init_logs():
    """Assert main.js calls initLogs()."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    assert re.search(r"\binitLogs\s*\(", content), (
        "main.js must call initLogs() to register log-since selector event listeners"
    )


@pytest.mark.unit
def test_window_bridge_retains_log_and_unit_globals():
    """Assert _logTabs, closeLogTab, switchLogTab, unitNameFor, and stemFromUnitName remain in the window bridge."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    bridge_start = content.find("Object.assign(window, {")
    assert bridge_start != -1, "Object.assign(window, { block not found in main.js"

    bridge_end = content.find("});", bridge_start)
    assert bridge_end != -1, "End of Object.assign(window, { ... }); block not found in main.js"

    bridge_body = content[bridge_start:bridge_end]
    for name in [
        "_logTabs",
        "closeLogTab",
        "switchLogTab",
        "unitNameFor",
        "stemFromUnitName",
    ]:
        assert name in bridge_body, (
            f"{name} must remain in the Object.assign(window, {{ ... }}) bridge; "
            "templates and e2e tests access it via window and would break without it"
        )
