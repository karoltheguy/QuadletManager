"""
Tests for making the Monaco editor follow the app's light/dark theme
(Issue #230).

These assert wiring that does not exist yet -- templates/partials/editor_pane.html
hardcodes `theme: 'vs-dark'` in the monaco.editor.create(...) options, and
static/main.js has no applyEditorTheme() function, never calls
monaco.editor.setTheme(...), and does not invoke any editor-theme sync from
toggleTheme() or the 'theme-updated' event handler. This is the RED phase of a
TDD cycle: all tests below are expected to fail until that wiring is
implemented.
"""
import os
import re

import pytest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
EDITOR_PANE_HTML_PATH = os.path.join(BASE_DIR, "templates", "partials", "editor_pane.html")
MAIN_JS_PATH = os.path.join(BASE_DIR, "static", "main.js")


def _editor_pane_html():
    with open(EDITOR_PANE_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _main_js():
    with open(MAIN_JS_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.mark.unit
def test_editor_pane_does_not_hardcode_vs_dark():
    html = _editor_pane_html()
    assert "theme: 'vs-dark'" not in html, (
        "Expected editor_pane.html to no longer hardcode theme: 'vs-dark' in the "
        "monaco.editor.create(...) options. A hardcoded 'vs-dark' theme means the "
        "editor never follows the app's light/dark theme toggle."
    )


@pytest.mark.unit
def test_editor_pane_calls_apply_editor_theme():
    html = _editor_pane_html()
    assert "applyEditorTheme" in html, (
        "Expected editor_pane.html to call applyEditorTheme() after creating the "
        "editor, so the editor's Monaco theme matches the app's current light/dark "
        "theme immediately on creation."
    )


@pytest.mark.unit
def test_main_js_defines_apply_editor_theme():
    js = _main_js()
    assert re.search(r"function applyEditorTheme", js) or re.search(r"applyEditorTheme\s*=", js), (
        "Expected static/main.js to define an applyEditorTheme() function (either as "
        "`function applyEditorTheme() {...}` or `applyEditorTheme = function() {...}`) "
        "that syncs the Monaco editor's theme with the app's current light/dark theme."
    )


@pytest.mark.unit
def test_main_js_calls_monaco_set_theme():
    js = _main_js()
    assert "monaco.editor.setTheme" in js, (
        "Expected static/main.js to call monaco.editor.setTheme(...) somewhere -- "
        "this is the Monaco API used to actually change the editor's rendered theme "
        "at runtime. Without this call, no code path can ever change the editor's "
        "theme after creation."
    )


@pytest.mark.unit
def test_toggle_theme_calls_apply_editor_theme():
    js = _main_js()
    match = re.search(r"function toggleTheme\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, (
        "Expected static/main.js to still contain a `function toggleTheme() { ... }` "
        "definition. If this regex no longer matches, toggleTheme's signature or "
        "structure changed -- update this test's extraction regex rather than letting "
        "it silently pass."
    )
    body = match.group(1)
    assert "applyEditorTheme" in body, (
        "Expected toggleTheme() to call applyEditorTheme() after flipping "
        "data-theme, so clicking the theme toggle immediately updates the Monaco "
        "editor's theme (mirroring the existing applyChartTheme() call in the same "
        "function)."
    )


@pytest.mark.unit
def test_theme_updated_handler_calls_apply_editor_theme():
    js = _main_js()
    match = re.search(
        r"addEventListener\('theme-updated',\s*function\s*\(\)\s*\{(.*?)\n\}\)",
        js,
        re.DOTALL,
    )
    assert match, (
        "Expected static/main.js to still contain a "
        "`document.body.addEventListener('theme-updated', function() { ... })` "
        "handler. If this regex no longer matches, the handler's signature or "
        "structure changed -- update this test's extraction regex rather than "
        "letting it silently pass."
    )
    body = match.group(1)
    assert "applyEditorTheme" in body, (
        "Expected the 'theme-updated' event handler to call applyEditorTheme(), so "
        "the Monaco editor's theme is resynced whenever the app's theme is updated "
        "externally (mirroring the existing applyChartTheme() call in the same "
        "handler)."
    )
