"""Tests for extracting modal dismissal handlers into ES module (modals.js).

These tests specify the migration where modal dismissal functions and listener
move out of main.js into static/modules/modals.js:
  - bindModalDismissal
  - setupModalDismissal
  - initModalDismissal
"""
import pathlib
import re

import pytest

from tests.js_source import static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

MODAL_FUNCTIONS = [
    "bindModalDismissal",
    "setupModalDismissal",
    "initModalDismissal",
]


@pytest.mark.unit
def test_modals_module_exports_its_functions():
    """Assert static/modules/modals.js exists and exports all three modal functions."""
    modals_js_path = REPO_ROOT / "static" / "modules" / "modals.js"
    assert modals_js_path.is_file(), f"Expected modals module file to exist at {modals_js_path}"

    content = modals_js_path.read_text(encoding="utf-8")
    for name in MODAL_FUNCTIONS:
        pattern = rf"\bexport\s+(?:async\s+)?function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/modals.js must export function {name}"
        )


@pytest.mark.unit
def test_modals_module_contains_dismissal_behavior():
    """Assert static/modules/modals.js contains the dismissal behavior."""
    modals_js_path = REPO_ROOT / "static" / "modules" / "modals.js"
    assert modals_js_path.is_file(), f"Expected modals module file to exist at {modals_js_path}"

    content = modals_js_path.read_text(encoding="utf-8")
    for term in ["Escape", "keydown", "modal-overlay", "dismissalSetup"]:
        assert term in content, (
            f"static/modules/modals.js must contain '{term}'"
        )


@pytest.mark.unit
def test_init_modal_dismissal_registers_htmx_listener():
    """Assert initModalDismissal registers htmx:afterSwap listener rather than at import time."""
    modals_js_path = REPO_ROOT / "static" / "modules" / "modals.js"
    assert modals_js_path.is_file(), f"Expected modals module file to exist at {modals_js_path}"

    content = modals_js_path.read_text(encoding="utf-8")
    assert "htmx:afterSwap" in content, (
        "static/modules/modals.js must contain 'htmx:afterSwap'"
    )

    init_match = re.search(r"\bexport\s+(?:async\s+)?function\s+initModalDismissal\b", content)
    assert init_match, "static/modules/modals.js must export function initModalDismissal"

    listener_match = re.search(r"addEventListener\(\s*['\"]htmx:afterSwap['\"]", content)
    assert listener_match, (
        "static/modules/modals.js must register an event listener for 'htmx:afterSwap'"
    )
    assert listener_match.start() > init_match.start(), (
        "htmx:afterSwap listener must appear after export function initModalDismissal"
    )


@pytest.mark.unit
def test_main_js_declares_none_of_the_modal_functions():
    """Assert main.js no longer declares any of the three modal functions."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    for name in MODAL_FUNCTIONS:
        assert not re.search(rf"\bfunction\s+{re.escape(name)}\b", content), (
            f"main.js must not declare function {name}"
        )


@pytest.mark.unit
def test_main_js_no_longer_registers_htmx_after_swap_modal_listener():
    """Assert main.js no longer registers the modal auto-setup htmx:afterSwap listener.

    main.js keeps an unrelated htmx:afterSwap listener, so this checks for the
    markers unique to the modal one rather than for the event name.
    """
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    for marker in ["dismissalSetup", "data-dismissal-setup"]:
        assert marker not in content, (
            f"main.js must no longer contain '{marker}'; the modal auto-setup "
            "listener belongs to static/modules/modals.js"
        )


@pytest.mark.unit
def test_main_js_imports_modal_functions_by_bare_specifier():
    """Assert main.js imports initModalDismissal from @qm/modals.

    setupModalDismissal left main.js with confirmDeleteFile in #443; see
    test_tree_module_imports_setup_modal_dismissal below.
    """
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    modals_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/modals['\"]", content)
    assert modals_match, "main.js must import from the '@qm/modals' bare specifier"

    imported = {n.strip() for n in modals_match.group(1).split(",") if n.strip()}
    assert "initModalDismissal" in imported, "main.js must import initModalDismissal from @qm/modals"


@pytest.mark.unit
def test_tree_module_imports_setup_modal_dismissal():
    """Assert tree.js imports setupModalDismissal, whose only caller now lives there."""
    tree_js_file = next((f for f in static_js_files() if f.name == "tree.js"), None)
    assert tree_js_file is not None, "tree.js not found in static_js_files()"

    content = tree_js_file.read_text(encoding="utf-8")
    modals_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/modals['\"]", content)
    assert modals_match, "tree.js must import from the '@qm/modals' bare specifier"

    imported = {n.strip() for n in modals_match.group(1).split(",") if n.strip()}
    assert "setupModalDismissal" in imported, "tree.js must import setupModalDismissal from @qm/modals"


@pytest.mark.unit
def test_main_js_calls_init_modal_dismissal():
    """Assert main.js calls initModalDismissal()."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    assert re.search(r"\binitModalDismissal\s*\(", content), (
        "main.js must call initModalDismissal()"
    )


@pytest.mark.unit
def test_window_bridge_no_longer_lists_setup_modal_dismissal():
    """Assert the Object.assign(window, { ... }) bridge in main.js no longer lists setupModalDismissal."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    bridge_start = content.find("Object.assign(window, {")
    assert bridge_start != -1, "Object.assign(window, { block not found in main.js"

    bridge_end = content.find("});", bridge_start)
    assert bridge_end != -1, "End of Object.assign(window, { ... }); block not found in main.js"

    bridge_body = content[bridge_start:bridge_end]
    assert "setupModalDismissal" not in bridge_body, (
        "setupModalDismissal must not be listed in the window bridge block"
    )


@pytest.mark.unit
def test_delete_confirm_call_site_does_not_use_window_prefix():
    """Assert window.setupModalDismissal does not appear anywhere in main.js."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    assert "window.setupModalDismissal" not in content, (
        "main.js must not call window.setupModalDismissal; invoke setupModalDismissal directly"
    )
