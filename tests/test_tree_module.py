"""Tests for extracting quadlet tree into ES module (tree.js).

These tests specify the migration for issue #443 where the quadlet tree functions
move out of main.js into:
  - static/modules/tree.js: toggleServerCollapse,
    restoreServerCollapseStates, handleServerCollapseKey,
    setSelectedQuadletBtn, reapplyQuadletSelection,
    restoreQuadletSelection, selectContainerStem, setActiveServer,
    applyStatusDots, showFileContextMenu, confirmDeleteFile,
    executeDeleteFile
"""
import pathlib
import re

import pytest

from tests.js_source import static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

TREE_EXPORT_FUNCTIONS = [
    "toggleServerCollapse",
    "restoreServerCollapseStates",
    "handleServerCollapseKey",
    "setSelectedQuadletBtn",
    "reapplyQuadletSelection",
    "restoreQuadletSelection",
    "selectContainerStem",
    "setActiveServer",
    "applyStatusDots",
    "showFileContextMenu",
    "confirmDeleteFile",
    "executeDeleteFile",
]

# handleServerCollapseKey is exported for addressability but has no caller
# outside tree.js, so main.js must not import it: tests/test_static_js_imports.py
# fails on an unused named import.
MAIN_JS_TREE_IMPORTS = [
    "toggleServerCollapse",
    "restoreServerCollapseStates",
    "setSelectedQuadletBtn",
    "reapplyQuadletSelection",
    "restoreQuadletSelection",
    "selectContainerStem",
    "setActiveServer",
    "applyStatusDots",
    "showFileContextMenu",
    "confirmDeleteFile",
    "executeDeleteFile",
]


@pytest.mark.unit
def test_tree_module_exports_its_functions():
    """Assert static/modules/tree.js exists and exports all twelve tree functions."""
    tree_js_path = REPO_ROOT / "static" / "modules" / "tree.js"
    assert tree_js_path.is_file(), (
        f"Expected tree module file to exist at {tree_js_path}; "
        "issue #443 extracts the quadlet tree into this module"
    )

    content = tree_js_path.read_text(encoding="utf-8")
    for name in TREE_EXPORT_FUNCTIONS:
        pattern = rf"\bexport\s+(?:async\s+)?function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/tree.js must export function {name}; "
            "it is part of the extracted tree API for issue #443"
        )


@pytest.mark.unit
def test_main_js_no_longer_declares_the_tree_functions():
    """Assert static/main.js no longer declares any of the twelve moved tree functions."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    for name in TREE_EXPORT_FUNCTIONS:
        assert not re.search(rf"\bfunction\s+{re.escape(name)}\b", content), (
            f"main.js must not declare function {name}; "
            "it has moved to static/modules/tree.js for issue #443"
        )


@pytest.mark.unit
def test_main_js_imports_the_tree_module():
    """Assert static/main.js imports the required tree functions from @qm/tree."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    tree_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/tree['\"]", content)
    assert tree_match, (
        "main.js must import from the '@qm/tree' bare specifier; issue #443"
    )

    imported_tree = {n.strip() for n in tree_match.group(1).split(",") if n.strip()}
    for name in MAIN_JS_TREE_IMPORTS:
        assert name in imported_tree, (
            f"main.js must import {name} from @qm/tree; issue #443"
        )
