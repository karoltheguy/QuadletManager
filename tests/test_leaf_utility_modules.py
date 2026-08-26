"""Tests for extracting leaf utility functions into ES modules (dom.js, color.js).

These tests specify the migration where nine leaf utility functions move out of
static/main.js into two new ES modules:
  - static/modules/dom.js: el, sendNotification, getRelativeTime, setStatText
  - static/modules/color.js: linearize, relativeLuminance, contrastRatio, onPrimaryFor, hexToRgba
"""
import pathlib
import re

import pytest

from tests.js_source import static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

DOM_UTILITIES = [
    "el",
    "sendNotification",
    "getRelativeTime",
    "setStatText",
]

COLOR_UTILITIES = [
    "linearize",
    "relativeLuminance",
    "contrastRatio",
    "onPrimaryFor",
    "hexToRgba",
]

ALL_LEAF_UTILITIES = DOM_UTILITIES + COLOR_UTILITIES


@pytest.mark.unit
def test_dom_module_exports_its_utilities():
    """Assert static/modules/dom.js exists and exports all four DOM utilities."""
    dom_js_path = REPO_ROOT / "static" / "modules" / "dom.js"
    assert dom_js_path.is_file(), f"Expected dom module file to exist at {dom_js_path}"

    content = dom_js_path.read_text(encoding="utf-8")
    for name in DOM_UTILITIES:
        pattern = rf"\bexport\s+(?:async\s+)?function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/dom.js must export function {name}"
        )


@pytest.mark.unit
def test_color_module_exports_its_utilities():
    """Assert static/modules/color.js exists and exports all five color utilities."""
    color_js_path = REPO_ROOT / "static" / "modules" / "color.js"
    assert color_js_path.is_file(), f"Expected color module file to exist at {color_js_path}"

    content = color_js_path.read_text(encoding="utf-8")
    for name in COLOR_UTILITIES:
        pattern = rf"\bexport\s+(?:async\s+)?function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/color.js must export function {name}"
        )


@pytest.mark.unit
def test_main_js_declares_none_of_the_leaf_utilities():
    """Assert main.js no longer declares any of the nine leaf utilities."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    offending_declarations = []
    for name in ALL_LEAF_UTILITIES:
        pattern = rf"^(?:(?:async\s+)?function|(?:const|let|var))\s+{re.escape(name)}\b"
        if re.search(pattern, content, re.MULTILINE):
            offending_declarations.append(name)

    assert not offending_declarations, (
        f"Found leaf utility declarations in main.js: {offending_declarations}"
    )


@pytest.mark.unit
def test_main_js_imports_the_leaf_utilities_by_bare_specifier():
    """Assert main.js imports each leaf module exactly while it still calls from it."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")

    # The import list must match what main.js actually calls, in both directions.
    # Some utilities (linearize, relativeLuminance, contrastRatio) are only used
    # by their own module, so importing them here would be dead weight that
    # eslint's no-unused-vars would flag.
    called = {
        name for name in ALL_LEAF_UTILITIES
        if re.search(rf"(?<![.\w$]){re.escape(name)}\s*\(", content)
    }

    dom_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/dom['\"]", content)
    assert dom_match, "main.js must import from the '@qm/dom' bare specifier"

    # main.js imports a leaf module only while it still calls something from it.
    # The theme extraction (#420) moved the last onPrimaryFor and hexToRgba call
    # sites into theme.js, so requiring this import unconditionally would force an
    # empty `import {} from '@qm/color'` that fetches the module for nothing.
    color_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/color['\"]", content)
    if called & set(COLOR_UTILITIES):
        assert color_match, "main.js must import from the '@qm/color' bare specifier"

    imported = {n.strip() for n in dom_match.group(1).split(",") if n.strip()}
    if color_match:
        imported |= {n.strip() for n in color_match.group(1).split(",") if n.strip()}

    missing = sorted(called - imported)
    assert not missing, f"main.js calls these but does not import them: {missing}"

    unused = sorted(imported - called)
    assert not unused, f"main.js imports these but never calls them: {unused}"


@pytest.mark.unit
def test_color_module_has_no_dom_dependencies():
    """Assert static/modules/color.js is pure and contains no DOM/browser references."""
    color_js_path = REPO_ROOT / "static" / "modules" / "color.js"
    assert color_js_path.is_file(), f"Expected color module file to exist at {color_js_path}"

    content = color_js_path.read_text(encoding="utf-8")
    forbidden = ["document", "window", "localStorage", "Notification"]
    found = [f for f in forbidden if f in content]
    assert not found, f"static/modules/color.js must not reference DOM globals: {found}"
