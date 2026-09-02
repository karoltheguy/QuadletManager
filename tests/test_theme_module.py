"""Tests for extracting theme functions into ES module (theme.js).

These tests specify the migration where twelve theme functions move out of
main.js into static/modules/theme.js:
  - toggleTheme
  - toggleDensity
  - initDensityRadio
  - toggleEditorTheme
  - initEditorThemeRadio
  - applyThemePreview
  - clearThemePreview
  - setEditorMode
  - getChartTheme
  - patchChartOptions
  - applyChartTheme
  - applyEditorTheme
"""
import pathlib
import re

import pytest

from tests.js_source import read_static_js, static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

THEME_FUNCTIONS = [
    "toggleTheme",
    "toggleDensity",
    "initDensityRadio",
    "toggleEditorTheme",
    "initEditorThemeRadio",
    "applyThemePreview",
    "clearThemePreview",
    "setEditorMode",
    "getChartTheme",
    "patchChartOptions",
    "applyChartTheme",
    "applyEditorTheme",
    "paintThemeSwatches",
]


@pytest.mark.unit
def test_theme_module_exports_its_functions():
    """Assert static/modules/theme.js exists and exports all thirteen theme functions."""
    theme_js_path = REPO_ROOT / "static" / "modules" / "theme.js"
    assert theme_js_path.is_file(), f"Expected theme module file to exist at {theme_js_path}"

    content = theme_js_path.read_text(encoding="utf-8")
    for name in THEME_FUNCTIONS:
        pattern = rf"\bexport\s+(?:async\s+)?function\s+{re.escape(name)}\b"
        assert re.search(pattern, content), (
            f"static/modules/theme.js must export function {name}"
        )


@pytest.mark.unit
def test_main_js_declares_none_of_the_theme_functions():
    """Assert main.js no longer declares any of the thirteen theme functions."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    offending_declarations = []
    for name in THEME_FUNCTIONS:
        pattern = rf"^(?:(?:async\s+)?function|(?:const|let|var))\s+{re.escape(name)}\b"
        if re.search(pattern, content, re.MULTILINE):
            offending_declarations.append(name)

    assert not offending_declarations, (
        f"Found theme function declarations in main.js: {offending_declarations}"
    )


@pytest.mark.unit
def test_main_js_imports_the_theme_functions_by_bare_specifier():
    """Assert main.js imports theme functions from @qm/theme."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")

    theme_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/theme['\"]", content)
    assert theme_match, "main.js must import from the '@qm/theme' bare specifier"

    imported = {n.strip() for n in theme_match.group(1).split(",") if n.strip()}

    called = {
        name for name in THEME_FUNCTIONS
        if re.search(rf"(?<![.\w$]){re.escape(name)}\s*\(", content)
    }

    missing = sorted(called - imported)
    assert not missing, f"main.js calls these but does not import them: {missing}"

    unused = sorted(imported - called)
    assert not unused, f"main.js imports these but never calls them: {unused}"


@pytest.mark.unit
def test_dead_health_history_chart_global_is_gone():
    """Assert dead global healthHistoryChart is removed from static JavaScript sources."""
    content = read_static_js()
    assert "healthHistoryChart" not in content, (
        "healthHistoryChart is never assigned and should be removed from static JavaScript source"
    )
