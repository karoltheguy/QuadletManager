"""Tests for extracting bottom panel and resize machinery into ES module (panel.js).

These tests specify the migration where bottom panel functions, resize handlers,
and keydown listeners move out of main.js into static/modules/panel.js:
  - openBottomPanel
  - fitActiveTerminal
  - toggleBottomPanel
  - toggleBottomPanelExpand
  - switchBottomTab
  - initPanel
"""
import pathlib
import re

import pytest

from tests.js_source import static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

PANEL_EXPORT_FUNCTIONS = [
    "openBottomPanel",
    "fitActiveTerminal",
    "toggleBottomPanel",
    "toggleBottomPanelExpand",
    "switchBottomTab",
    "initResizableHandles",
    "initPanel",
]

PANEL_FUNCTIONS = [
    "openBottomPanel",
    "fitActiveTerminal",
    "toggleBottomPanel",
    "toggleBottomPanelExpand",
    "switchBottomTab",
]

RESIZE_CONSTANTS = [
    "SIDEBAR_MIN",
    "SIDEBAR_MAX",
    "INSPECTOR_MIN",
    "INSPECTOR_MAX",
    "SETTINGS_SIDENAV_MIN",
    "SETTINGS_SIDENAV_MAX",
    "BOTTOM_PANEL_MIN",
    "BOTTOM_PANEL_MAX",
]

RESIZE_HANDLES = [
    "resize-handle-left",
    "settings-sidenav-resize-handle",
    "resize-handle-right",
    "bottom-panel-resize-handle",
]


@pytest.mark.unit
def test_panel_module_exports_its_functions():
    """Assert static/modules/panel.js exists and exports all six panel functions."""
    panel_js_path = REPO_ROOT / "static" / "modules" / "panel.js"
    assert panel_js_path.is_file(), f"Expected panel module file to exist at {panel_js_path}"

    content = panel_js_path.read_text(encoding="utf-8")
    for name in PANEL_EXPORT_FUNCTIONS:
        pattern = rf"\bexport\s+function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/panel.js must export function {name}"
        )


@pytest.mark.unit
def test_panel_module_carries_resize_machinery():
    """Assert static/modules/panel.js contains makeDraggable, all four handle IDs, and six constants."""
    panel_js_path = REPO_ROOT / "static" / "modules" / "panel.js"
    assert panel_js_path.is_file(), f"Expected panel module file to exist at {panel_js_path}"

    content = panel_js_path.read_text(encoding="utf-8")
    assert "makeDraggable" in content, (
        "static/modules/panel.js must contain 'makeDraggable'"
    )
    for handle_id in RESIZE_HANDLES:
        assert handle_id in content, (
            f"static/modules/panel.js must contain handle id '{handle_id}'"
        )
    for const_name in RESIZE_CONSTANTS:
        assert const_name in content, (
            f"static/modules/panel.js must contain constant '{const_name}'"
        )


@pytest.mark.unit
def test_init_panel_owns_the_keydown_listener():
    """Assert the Ctrl+1 / Ctrl+2 keydown listener registers inside initPanel.

    It is the cluster's only parse-time registration. initResizableHandles and
    the qm-bottom-tab restore are already called from main.js's DOMContentLoaded
    handler, so they stay there and are not initPanel's business.
    """
    panel_js_path = REPO_ROOT / "static" / "modules" / "panel.js"
    assert panel_js_path.is_file(), f"Expected panel module file to exist at {panel_js_path}"

    content = panel_js_path.read_text(encoding="utf-8")
    init_match = re.search(r"\bexport\s+function\s+initPanel\b", content)
    assert init_match, "static/modules/panel.js must export function initPanel"

    listener_match = re.search(r"addEventListener\(\s*['\"]keydown['\"]", content)
    assert listener_match, (
        "static/modules/panel.js must register an event listener for 'keydown'"
    )
    assert listener_match.start() > init_match.start(), (
        "the 'keydown' listener must register inside initPanel, not at module "
        "top level, so importing static/modules/panel.js has no side effect"
    )


@pytest.mark.unit
def test_panel_module_uses_shared_state_module():
    """Assert static/modules/panel.js imports _terminalTabs from @qm/state and does not use window._terminalTabs."""
    panel_js_path = REPO_ROOT / "static" / "modules" / "panel.js"
    assert panel_js_path.is_file(), f"Expected panel module file to exist at {panel_js_path}"

    content = panel_js_path.read_text(encoding="utf-8")
    state_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/state['\"]", content)
    assert state_match, "static/modules/panel.js must import from the '@qm/state' bare specifier"

    imported = {n.strip() for n in state_match.group(1).split(",") if n.strip()}
    assert "_terminalTabs" in imported, (
        "static/modules/panel.js must import '_terminalTabs' from @qm/state"
    )
    assert "window._terminalTabs" not in content, (
        "static/modules/panel.js must not reference 'window._terminalTabs'; use imported '_terminalTabs'"
    )


@pytest.mark.unit
def test_main_js_declares_none_of_the_panel_functions():
    """Assert main.js no longer declares any of the five panel functions."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    for name in PANEL_FUNCTIONS:
        assert not re.search(rf"\bfunction\s+{re.escape(name)}\b", content), (
            f"main.js must not declare function {name}"
        )


@pytest.mark.unit
def test_main_js_no_longer_holds_resize_machinery():
    """Assert main.js no longer holds makeDraggable or the four resize handle IDs."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    assert "makeDraggable" not in content, (
        "main.js must no longer contain 'makeDraggable'; resize machinery belongs in static/modules/panel.js"
    )
    for handle_id in RESIZE_HANDLES:
        assert handle_id not in content, (
            f"main.js must no longer contain '{handle_id}'; resize handle setup belongs in static/modules/panel.js"
        )


@pytest.mark.unit
def test_main_js_imports_panel_functions_by_bare_specifier():
    """Assert main.js imports every panel name it still calls from @qm/panel."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    panel_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/panel['\"]", content)
    assert panel_match, "main.js must import from the '@qm/panel' bare specifier"

    imported = {n.strip() for n in panel_match.group(1).split(",") if n.strip()}
    # main.js still calls each of these: openBottomPanel from the SSE and
    # terminal paths, switchBottomTab and the two toggles from the delegated
    # handler map, initPanel from bootstrap. A missing import is a runtime
    # error no source-reading test would otherwise catch.
    for name in [
        "openBottomPanel",
        "switchBottomTab",
        "toggleBottomPanel",
        "toggleBottomPanelExpand",
        "initResizableHandles",
        "initPanel",
    ]:
        assert name in imported, f"main.js must import {name} from @qm/panel"


@pytest.mark.unit
def test_main_js_calls_init_panel():
    """Assert main.js calls initPanel()."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    assert re.search(r"\binitPanel\s*\(", content), (
        "main.js must call initPanel()"
    )


@pytest.mark.unit
def test_window_bridge_retains_open_bottom_panel():
    """Assert openBottomPanel remains in the Object.assign(window, { ... }) bridge in main.js."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    bridge_start = content.find("Object.assign(window, {")
    assert bridge_start != -1, "Object.assign(window, { block not found in main.js"

    bridge_end = content.find("});", bridge_start)
    assert bridge_end != -1, "End of Object.assign(window, { ... }); block not found in main.js"

    bridge_body = content[bridge_start:bridge_end]
    assert "openBottomPanel" in bridge_body, (
        "openBottomPanel must remain in the Object.assign(window, { ... }) bridge; "
        "tests/e2e/test_terminal_connect.py and tests/e2e/test_log_tabs.py call it "
        "via page.evaluate('openBottomPanel(...)') and would silently break without it"
    )
