"""Tests for extracting terminal WebSocket client and tab management into ES module (terminal.js).

These tests specify the migration for issue #430 where terminal connection functions,
xterm tab lifecycle management, and shell selection move out of main.js into:
  - static/modules/terminal.js: loadFitAddon, showTerminalMessage,
    findActualRunningContainerName, getTerminalShellCommand, connectTerminal,
    createTerminalTab, switchTerminalTab, disposeTerminalSession,
    removeTerminalDOM, handleClosedTabFallback, closeTerminalTab,
    sessionAddNew, initTerminal
"""
import pathlib
import re

import pytest

from tests.js_source import read_static_js, static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

TERMINAL_EXPORT_FUNCTIONS = [
    "loadFitAddon",
    "showTerminalMessage",
    "findActualRunningContainerName",
    "getTerminalShellCommand",
    "connectTerminal",
    "createTerminalTab",
    "switchTerminalTab",
    "disposeTerminalSession",
    "removeTerminalDOM",
    "handleClosedTabFallback",
    "closeTerminalTab",
    "sessionAddNew",
    "initTerminal",
]

MOVED_FUNCTIONS = [
    "loadFitAddon",
    "showTerminalMessage",
    "findActualRunningContainerName",
    "getTerminalShellCommand",
    "connectTerminal",
    "createTerminalTab",
    "switchTerminalTab",
    "disposeTerminalSession",
    "removeTerminalDOM",
    "handleClosedTabFallback",
    "closeTerminalTab",
    "sessionAddNew",
]

MAIN_JS_TERMINAL_IMPORTS = [
    "connectTerminal",
    "createTerminalTab",
    "loadFitAddon",
    "switchTerminalTab",
    "closeTerminalTab",
    "sessionAddNew",
    "initTerminal",
]

WINDOW_BRIDGE_TERMINAL_NAMES = [
    "_terminalTabs",
    "closeTerminalTab",
    "switchTerminalTab",
]


@pytest.mark.unit
def test_terminal_module_exports_its_functions():
    """Assert static/modules/terminal.js exists and exports all thirteen terminal functions."""
    terminal_js_path = REPO_ROOT / "static" / "modules" / "terminal.js"
    assert terminal_js_path.is_file(), (
        f"Expected terminal module file to exist at {terminal_js_path}; "
        "issue #430 extracts the /ws/exec terminal client into this module"
    )

    content = terminal_js_path.read_text(encoding="utf-8")
    for name in TERMINAL_EXPORT_FUNCTIONS:
        pattern = rf"\bexport\s+function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/terminal.js must export function {name}; "
            "it is part of the extracted terminal client API"
        )


@pytest.mark.unit
def test_terminal_module_declares_terminal_global_for_eslint():
    """Assert static/modules/terminal.js carries an eslint /* global ... */ comment naming Terminal."""
    terminal_js_path = REPO_ROOT / "static" / "modules" / "terminal.js"
    assert terminal_js_path.is_file(), (
        f"Expected terminal module file to exist at {terminal_js_path}; "
        "issue #430 extracts the /ws/exec terminal client into this module"
    )

    content = terminal_js_path.read_text(encoding="utf-8")
    global_comment_match = re.search(r"/\*\s*global\b([^*]*)\*/", content)
    assert global_comment_match, (
        "static/modules/terminal.js must include an eslint '/* global ... */' comment "
        "declaring globals provided outside the ES module graph"
    )
    globals_declared = {g.strip() for g in global_comment_match.group(1).split(",") if g.strip()}
    assert "Terminal" in globals_declared or re.search(r"\bTerminal\b", global_comment_match.group(1)), (
        "static/modules/terminal.js must declare 'Terminal' in its /* global ... */ header "
        "so the CI eslint gate passes for the vendored xterm bundle global"
    )


@pytest.mark.unit
def test_init_terminal_owns_event_listeners():
    """Assert the change listener and resize listener register inside initTerminal.

    Importing a module must have no side effects, so the change event listener
    on #terminal-shell-select and the window resize listener must register inside
    the exported initTerminal function rather than at module top level.
    """
    terminal_js_path = REPO_ROOT / "static" / "modules" / "terminal.js"
    assert terminal_js_path.is_file(), (
        f"Expected terminal module file to exist at {terminal_js_path}; "
        "issue #430 extracts the /ws/exec terminal client into this module"
    )

    content = terminal_js_path.read_text(encoding="utf-8")
    init_match = re.search(r"\bexport\s+function\s+initTerminal\b", content)
    assert init_match, "static/modules/terminal.js must export function initTerminal"

    change_listener_match = re.search(r"addEventListener\(\s*['\"]change['\"]", content)
    assert change_listener_match, (
        "static/modules/terminal.js must register an event listener for 'change'"
    )
    assert change_listener_match.start() > init_match.start(), (
        "the 'change' listener must register inside initTerminal, not at module "
        "top level, so importing static/modules/terminal.js has no side effects"
    )

    resize_listener_match = re.search(r"addEventListener\(\s*['\"]resize['\"]", content)
    assert resize_listener_match, (
        "static/modules/terminal.js must register an event listener for 'resize'"
    )
    assert resize_listener_match.start() > init_match.start(), (
        "the 'resize' listener must register inside initTerminal, not at module "
        "top level, so importing static/modules/terminal.js has no side effects"
    )


@pytest.mark.unit
def test_terminal_module_imports_from_state_module():
    """Assert static/modules/terminal.js imports state, _terminalTabs, and runningContainersBySid from @qm/state."""
    terminal_js_path = REPO_ROOT / "static" / "modules" / "terminal.js"
    assert terminal_js_path.is_file(), (
        f"Expected terminal module file to exist at {terminal_js_path}; "
        "issue #430 extracts the /ws/exec terminal client into this module"
    )

    content = terminal_js_path.read_text(encoding="utf-8")
    state_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/state['\"]", content)
    assert state_match, "static/modules/terminal.js must import from the '@qm/state' bare specifier"

    imported = {n.strip() for n in state_match.group(1).split(",") if n.strip()}
    for name in ["state", "_terminalTabs", "runningContainersBySid"]:
        assert name in imported, (
            f"static/modules/terminal.js must import '{name}' from @qm/state to access shared application state"
        )


@pytest.mark.unit
def test_terminal_module_imports_from_panel_module():
    """Assert static/modules/terminal.js imports openBottomPanel, switchBottomTab, and refreshSessionsStripVisibility from @qm/panel."""
    terminal_js_path = REPO_ROOT / "static" / "modules" / "terminal.js"
    assert terminal_js_path.is_file(), (
        f"Expected terminal module file to exist at {terminal_js_path}; "
        "issue #430 extracts the /ws/exec terminal client into this module"
    )

    content = terminal_js_path.read_text(encoding="utf-8")
    panel_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/panel['\"]", content)
    assert panel_match, "static/modules/terminal.js must import from the '@qm/panel' bare specifier"

    imported = {n.strip() for n in panel_match.group(1).split(",") if n.strip()}
    for name in ["openBottomPanel", "switchBottomTab", "refreshSessionsStripVisibility"]:
        assert name in imported, (
            f"static/modules/terminal.js must import '{name}' from @qm/panel to manage bottom panel and tab visibility"
        )


@pytest.mark.unit
def test_terminal_module_imports_from_logs_module():
    """Assert static/modules/terminal.js imports tailLogsFromPanel from @qm/logs."""
    terminal_js_path = REPO_ROOT / "static" / "modules" / "terminal.js"
    assert terminal_js_path.is_file(), (
        f"Expected terminal module file to exist at {terminal_js_path}; "
        "issue #430 extracts the /ws/exec terminal client into this module"
    )

    content = terminal_js_path.read_text(encoding="utf-8")
    logs_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/logs['\"]", content)
    assert logs_match, "static/modules/terminal.js must import from the '@qm/logs' bare specifier"

    imported = {n.strip() for n in logs_match.group(1).split(",") if n.strip()}
    assert "tailLogsFromPanel" in imported, (
        "static/modules/terminal.js must import 'tailLogsFromPanel' from @qm/logs "
        "for sessionAddNew dispatching to the active logs pane"
    )


@pytest.mark.unit
def test_hide_terminal_section_is_removed_from_all_static_js():
    """Assert hideTerminalSection is completely removed from all non-vendor static JS files."""
    static_js = read_static_js()
    assert "hideTerminalSection" not in static_js, (
        "hideTerminalSection was dead code (terminals stopped auto-closing on deselect) "
        "and must be removed from all non-vendor static JS files rather than moved to terminal.js"
    )


@pytest.mark.unit
def test_main_js_declares_none_of_the_moved_functions():
    """Assert main.js no longer declares any of the twelve moved terminal functions or setupShellSelector."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    for name in MOVED_FUNCTIONS:
        assert not re.search(rf"\bfunction\s+{re.escape(name)}\b", content), (
            f"main.js must not declare function {name}; it has moved to its dedicated ES module"
        )
    assert not re.search(r"\bconst\s+setupShellSelector\b", content), (
        "main.js must not declare setupShellSelector; listener registration moved to initTerminal in static/modules/terminal.js"
    )


@pytest.mark.unit
def test_main_js_imports_terminal_functions_by_bare_specifier():
    """Assert main.js imports exactly the required terminal names from @qm/terminal."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    terminal_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/terminal['\"]", content)
    assert terminal_match, "main.js must import from the '@qm/terminal' bare specifier"

    imported_terminal = {n.strip() for n in terminal_match.group(1).split(",") if n.strip()}
    for name in MAIN_JS_TERMINAL_IMPORTS:
        assert name in imported_terminal, f"main.js must import {name} from @qm/terminal"
    assert imported_terminal == set(MAIN_JS_TERMINAL_IMPORTS), (
        f"main.js must import exactly {MAIN_JS_TERMINAL_IMPORTS} from @qm/terminal with no unused imports"
    )


@pytest.mark.unit
def test_main_js_calls_init_terminal():
    """Assert main.js calls initTerminal()."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    assert re.search(r"\binitTerminal\s*\(", content), (
        "main.js must call initTerminal() to register shell selector change and window resize event listeners"
    )


@pytest.mark.unit
def test_window_bridge_retains_terminal_globals():
    """Assert _terminalTabs, closeTerminalTab, and switchTerminalTab remain in the window bridge."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    bridge_start = content.find("Object.assign(window, {")
    assert bridge_start != -1, "Object.assign(window, { block not found in main.js"

    bridge_end = content.find("});", bridge_start)
    assert bridge_end != -1, "End of Object.assign(window, { ... }); block not found in main.js"

    bridge_body = content[bridge_start:bridge_end]
    for name in WINDOW_BRIDGE_TERMINAL_NAMES:
        assert name in bridge_body, (
            f"{name} must remain in the Object.assign(window, {{ ... }}) bridge; "
            "templates and e2e tests access it via window and would break without it"
        )
