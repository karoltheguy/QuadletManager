"""Tests for extracting Inspector pane into ES module (inspector.js).

These tests specify the migration for issue #441 where the Inspector pane functions
move out of main.js into:
  - static/modules/inspector.js: updateInspectorStatsCard,
    updateInspectorActivityLog, syncInspectorToggleBtn,
    toggleInspectorExpand
"""
import pathlib
import re

import pytest

from tests.js_source import static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

INSPECTOR_EXPORT_FUNCTIONS = [
    "updateInspectorStatsCard",
    "updateInspectorActivityLog",
    "syncInspectorToggleBtn",
    "toggleInspectorExpand",
]

MAIN_JS_INSPECTOR_IMPORTS = [
    "updateInspectorStatsCard",
    "updateInspectorActivityLog",
    "syncInspectorToggleBtn",
    "toggleInspectorExpand",
]


@pytest.mark.unit
def test_inspector_module_exports_its_functions():
    """Assert static/modules/inspector.js exists and exports all four inspector functions."""
    inspector_js_path = REPO_ROOT / "static" / "modules" / "inspector.js"
    assert inspector_js_path.is_file(), (
        f"Expected inspector module file to exist at {inspector_js_path}; "
        "issue #441 extracts the Inspector pane into this module"
    )

    content = inspector_js_path.read_text(encoding="utf-8")
    for name in INSPECTOR_EXPORT_FUNCTIONS:
        pattern = rf"\bexport\s+function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/inspector.js must export function {name}; "
            "it is part of the extracted inspector API for issue #441"
        )


@pytest.mark.unit
def test_main_js_no_longer_declares_the_inspector_functions():
    """Assert static/main.js no longer declares any of the four moved inspector functions."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    for name in INSPECTOR_EXPORT_FUNCTIONS:
        assert not re.search(rf"\bfunction\s+{re.escape(name)}\b", content), (
            f"main.js must not declare function {name}; "
            "it has moved to static/modules/inspector.js for issue #441"
        )


@pytest.mark.unit
def test_main_js_imports_the_inspector_module():
    """Assert static/main.js imports the required inspector functions from @qm/inspector."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    inspector_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/inspector['\"]", content)
    assert inspector_match, (
        "main.js must import from the '@qm/inspector' bare specifier; issue #441"
    )

    imported_inspector = {n.strip() for n in inspector_match.group(1).split(",") if n.strip()}
    for name in MAIN_JS_INSPECTOR_IMPORTS:
        assert name in imported_inspector, (
            f"main.js must import {name} from @qm/inspector; issue #441"
        )
