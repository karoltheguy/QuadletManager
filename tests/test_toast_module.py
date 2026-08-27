"""Tests for extracting toast notification helper into ES module (toast.js).

These tests specify the migration where inline toast markup construction in
static/main.js is replaced with a showToast helper in static/modules/toast.js:
  - htmx:responseError handler (danger toast)
  - user-updated handler (success toast)
  - file_changed SSE handler (warning toast)
"""
import pathlib
import re

import pytest

from tests.js_source import static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent


@pytest.mark.unit
def test_toast_module_exports_show_toast():
    """Assert static/modules/toast.js exists and exports showToast."""
    toast_js_path = REPO_ROOT / "static" / "modules" / "toast.js"
    assert toast_js_path.is_file(), f"Expected toast module file to exist at {toast_js_path}"

    content = toast_js_path.read_text(encoding="utf-8")
    pattern = r"\bexport\s+(?:async\s+)?function\s+showToast\b"
    assert re.search(pattern, content), (
        "static/modules/toast.js must export function showToast"
    )


@pytest.mark.unit
def test_show_toast_implementation_manipulates_status_toast_via_text_content():
    """Assert showToast references status-toast, assigns via textContent, and contains no innerHTML."""
    toast_js_path = REPO_ROOT / "static" / "modules" / "toast.js"
    assert toast_js_path.is_file(), f"Expected toast module file to exist at {toast_js_path}"

    content = toast_js_path.read_text(encoding="utf-8")
    assert "status-toast" in content, (
        "static/modules/toast.js must reference the 'status-toast' element"
    )
    assert "textContent" in content, (
        "static/modules/toast.js must assign content via textContent"
    )
    assert "innerHTML" not in content, (
        "static/modules/toast.js must not contain innerHTML"
    )


@pytest.mark.unit
def test_show_toast_builds_class_name_from_kind():
    """Assert showToast builds class names containing toast-msg and toast-enter."""
    toast_js_path = REPO_ROOT / "static" / "modules" / "toast.js"
    assert toast_js_path.is_file(), f"Expected toast module file to exist at {toast_js_path}"

    content = toast_js_path.read_text(encoding="utf-8")
    assert "toast-msg" in content, (
        "static/modules/toast.js must build classes containing 'toast-msg'"
    )
    assert "toast-enter" in content, (
        "static/modules/toast.js must build classes containing 'toast-enter'"
    )


@pytest.mark.unit
def test_show_toast_auto_dismisses():
    """Assert showToast auto-dismisses after 8000ms checking for toast-enter."""
    toast_js_path = REPO_ROOT / "static" / "modules" / "toast.js"
    assert toast_js_path.is_file(), f"Expected toast module file to exist at {toast_js_path}"

    content = toast_js_path.read_text(encoding="utf-8")
    assert "8000" in content, (
        "static/modules/toast.js must include an 8000ms auto-dismiss timeout"
    )
    assert "toast-enter" in content, (
        "static/modules/toast.js must check for 'toast-enter' on auto-dismiss"
    )


@pytest.mark.unit
def test_main_js_no_longer_builds_toast_markup_inline():
    """Assert main.js no longer builds toast markup inline for danger, success, or warning."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    inline_toast_classes = [
        "toast-msg toast-danger",
        "toast-msg toast-success",
        "toast-msg toast-warning",
    ]
    found = [cls for cls in inline_toast_classes if cls in content]
    assert not found, (
        f"Found inline toast class strings in main.js: {found}"
    )


@pytest.mark.unit
def test_event_handlers_call_show_toast():
    """Assert htmx:responseError, user-updated, and file_changed handlers call showToast."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    events = ["htmx:responseError", "user-updated", "file_changed"]
    for event_name in events:
        match = re.search(
            rf"addEventListener\(\s*['\"]{re.escape(event_name)}['\"]", content
        )
        assert match, f"Event handler registration for '{event_name}' not found in main.js"
        window = content[match.start() : match.start() + 1500]
        assert "showToast" in window, (
            f"Event handler for '{event_name}' must call showToast within 1500 chars of event registration"
        )


@pytest.mark.unit
def test_main_js_imports_show_toast_by_bare_specifier():
    """Assert main.js imports showToast from the @qm/toast bare specifier."""
    main_js_file = next((f for f in static_js_files() if f.name == "main.js"), None)
    assert main_js_file is not None, "main.js not found in static_js_files()"

    content = main_js_file.read_text(encoding="utf-8")
    toast_match = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]@qm/toast['\"]", content)
    assert toast_match, "main.js must import from the '@qm/toast' bare specifier"

    imported = {n.strip() for n in toast_match.group(1).split(",") if n.strip()}
    assert "showToast" in imported, "main.js must import showToast from @qm/toast"
