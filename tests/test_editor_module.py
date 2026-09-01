"""Tests for extracting Monaco editor validate/save cluster into ES module (editor.js).

These tests specify the migration for issue #435 where Monaco editor validation,
save handling, dirty-state listeners, and editor configuration helpers move out of
main.js into:
  - static/modules/editor.js: validateQuadlet, saveQuadlet, initEditor
"""
import pathlib
import re

import pytest

from tests.js_source import static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

EDITOR_EXPORT_FUNCTIONS = [
    "validateQuadlet",
    "saveQuadlet",
    "initEditor",
]

MOVED_FUNCTIONS = [
    "validateQuadlet",
    "saveQuadlet",
    "throwValidationRequestError",
]

MAIN_JS_EDITOR_IMPORTS = [
    "validateQuadlet",
    "saveQuadlet",
    "initEditor",
]


@pytest.mark.unit
def test_editor_module_exists():
    """Assert static/modules/editor.js exists."""
    editor_js_path = REPO_ROOT / "static" / "modules" / "editor.js"
    assert editor_js_path.is_file(), (
        f"Expected editor module file to exist at {editor_js_path}; "
        "issue #435 extracts the Monaco editor validate/save cluster into this module"
    )


@pytest.mark.unit
@pytest.mark.parametrize("name", EDITOR_EXPORT_FUNCTIONS)
def test_editor_module_exports_functions(name):
    """Assert static/modules/editor.js exports each required editor function."""
    editor_js_path = REPO_ROOT / "static" / "modules" / "editor.js"
    assert editor_js_path.is_file(), (
        f"Expected editor module file to exist at {editor_js_path}; "
        "issue #435 extracts the Monaco editor validate/save cluster into this module"
    )

    content = editor_js_path.read_text(encoding="utf-8")
    pattern = rf"(?:\bexport\s+(?:async\s+)?function\s+{re.escape(name)}\b|\bexport\s*\{{[^}}]*\b{re.escape(name)}\b)"
    assert re.search(pattern, content), (
        f"static/modules/editor.js must export {name}; "
        "it is part of the extracted editor API"
    )


@pytest.mark.unit
def test_editor_module_declares_globals_for_eslint():
    """Assert static/modules/editor.js starts with an eslint /* global ... */ comment naming monaco and require."""
    editor_js_path = REPO_ROOT / "static" / "modules" / "editor.js"
    assert editor_js_path.is_file(), (
        f"Expected editor module file to exist at {editor_js_path}; "
        "issue #435 extracts the Monaco editor validate/save cluster into this module"
    )

    lines = editor_js_path.read_text(encoding="utf-8").splitlines()[:5]
    header = "\n".join(lines)
    global_comment_match = re.search(r"/\*\s*global\b([^*]*)\*/", header)
    assert global_comment_match, (
        "static/modules/editor.js must start with an eslint '/* global ... */' comment "
        "in its first 5 lines declaring vendor globals"
    )
    globals_declared = {g.strip() for g in global_comment_match.group(1).split(",") if g.strip()}
    assert "monaco" in globals_declared or re.search(r"\bmonaco\b", global_comment_match.group(1)), (
        "static/modules/editor.js must declare 'monaco' in its /* global ... */ comment header "
        "so the CI eslint gate passes for the vendored Monaco editor global"
    )
    assert "require" in globals_declared or re.search(r"\brequire\b", global_comment_match.group(1)), (
        "static/modules/editor.js must declare 'require' in its /* global ... */ comment header "
        "so the CI eslint gate passes for the vendored Monaco AMD loader global"
    )


@pytest.mark.unit
def test_editor_module_contains_htmx_confirm_listener():
    """Assert static/modules/editor.js contains the htmx:confirm listener guarding #editor-pane swaps."""
    editor_js_path = REPO_ROOT / "static" / "modules" / "editor.js"
    assert editor_js_path.is_file(), (
        f"Expected editor module file to exist at {editor_js_path}; "
        "issue #435 extracts the Monaco editor validate/save cluster into this module"
    )

    content = editor_js_path.read_text(encoding="utf-8")
    assert "htmx:confirm" in content, (
        "static/modules/editor.js must contain 'htmx:confirm' listener to guard unsaved editor pane swaps"
    )
    assert "_editorDirty" in content, (
        "static/modules/editor.js must check '_editorDirty' in the htmx:confirm listener"
    )


@pytest.mark.unit
def test_editor_module_contains_quadlet_saved_listener():
    """Assert static/modules/editor.js contains the quadlet-saved listener."""
    editor_js_path = REPO_ROOT / "static" / "modules" / "editor.js"
    assert editor_js_path.is_file(), (
        f"Expected editor module file to exist at {editor_js_path}; "
        "issue #435 extracts the Monaco editor validate/save cluster into this module"
    )

    content = editor_js_path.read_text(encoding="utf-8")
    assert "quadlet-saved" in content, (
        "static/modules/editor.js must contain 'quadlet-saved' event listener"
    )
    assert "editorDirty = false" in content, (
        "static/modules/editor.js must clear its editorDirty flag on quadlet-saved"
    )


@pytest.mark.unit
def test_monaco_require_config_moved_to_editor_module():
    """Assert static/modules/editor.js configures Monaco path and static/main.js does not."""
    editor_js_path = REPO_ROOT / "static" / "modules" / "editor.js"
    assert editor_js_path.is_file(), (
        f"Expected editor module file to exist at {editor_js_path}; "
        "issue #435 extracts the Monaco editor validate/save cluster into this module"
    )

    editor_content = editor_js_path.read_text(encoding="utf-8")
    assert "/static/vendor/monaco/vs" in editor_content, (
        "static/modules/editor.js must contain the Monaco require.config call for '/static/vendor/monaco/vs'"
    )

    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"
    main_content = main_js_file.read_text(encoding="utf-8")
    assert "/static/vendor/monaco/vs" not in main_content, (
        "main.js must no longer contain the Monaco require.config call for '/static/vendor/monaco/vs'"
    )


@pytest.mark.unit
def test_main_js_imports_editor_functions_by_bare_specifier():
    """Assert static/main.js imports validateQuadlet, saveQuadlet, and initEditor from @qm/editor."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    editor_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/editor['\"]", content)
    assert editor_match, "main.js must import from the '@qm/editor' bare specifier"

    imported_editor = {n.strip() for n in editor_match.group(1).split(",") if n.strip()}
    for name in MAIN_JS_EDITOR_IMPORTS:
        assert name in imported_editor, f"main.js must import {name} from @qm/editor"


@pytest.mark.unit
@pytest.mark.parametrize("name", MOVED_FUNCTIONS)
def test_main_js_declares_none_of_the_moved_functions(name):
    """Assert static/main.js no longer declares any of the moved editor functions."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    assert not re.search(rf"\bfunction\s+{re.escape(name)}\b", content), (
        f"main.js must not declare function {name}; it has moved to static/modules/editor.js"
    )


@pytest.mark.unit
def test_main_js_calls_init_editor():
    """Assert static/main.js calls initEditor()."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    assert re.search(r"\binitEditor\s*\(", content), (
        "main.js must call initEditor() to set up Monaco configuration and editor event listeners"
    )


@pytest.mark.unit
def test_main_js_no_longer_contains_editor_event_listeners():
    """Assert static/main.js contains neither htmx:confirm nor quadlet-saved listeners."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    assert "htmx:confirm" not in content, (
        "main.js must no longer contain 'htmx:confirm'; the listener moved to static/modules/editor.js"
    )
    assert "quadlet-saved" not in content, (
        "main.js must no longer contain 'quadlet-saved'; the listener moved to static/modules/editor.js"
    )
