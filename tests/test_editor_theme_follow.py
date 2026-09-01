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

from tests.js_source import read_static_js

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
EDITOR_PANE_HTML_PATH = os.path.join(BASE_DIR, "templates", "partials", "editor_pane.html")
EDITOR_JS_PATH = os.path.join(BASE_DIR, "static", "modules", "editor.js")


def _editor_pane_html():
    with open(EDITOR_PANE_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _editor_js():
    """Source of static/modules/editor.js.

    #468 moved the editor pane's mount code out of the template and into
    mountEditorPane() here, so the theme wiring these tests guard lives in the
    module now. Asserting against the template would pass vacuously.
    """
    with open(EDITOR_JS_PATH, encoding="utf-8") as f:
        return f.read()


def _main_js():
    return read_static_js()


@pytest.mark.unit
def test_editor_pane_does_not_hardcode_vs_dark():
    html = _editor_js()
    assert "theme: 'vs-dark'" not in html, (
        "Expected mountEditorPane() to no longer hardcode theme: 'vs-dark' in the "
        "monaco.editor.create(...) options. A hardcoded 'vs-dark' theme means the "
        "editor never follows the app's light/dark theme toggle."
    )


@pytest.mark.unit
def test_editor_pane_calls_apply_editor_theme():
    html = _editor_js()
    assert "applyEditorTheme" in html, (
        "Expected mountEditorPane() to call applyEditorTheme() after creating the "
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


# ---------------------------------------------------------------------------
# Issue #231: persist an explicit editor-theme preference (follow/light/dark)
# in localStorage under the key `qm-editor-theme`, mirroring the existing
# UI-density pattern (`qm-density`, toggleDensity()/initDensityRadio() in
# static/main.js), and add a tri-state radio group in templates/dashboard.html
# (id `density-section`-adjacent, name="editor_theme", values follow/light/dark).
#
# None of this wiring exists yet: static/main.js has no `qm-editor-theme`
# localStorage key and no getItem/setItem calls for it, and
# templates/dashboard.html has no `name="editor_theme"` radio group. This is
# the RED phase of a TDD cycle: all tests below are expected to fail until
# that wiring is implemented.
# ---------------------------------------------------------------------------

DASHBOARD_HTML_PATH = os.path.join(BASE_DIR, "templates", "dashboard.html")


def _dashboard_html():
    with open(DASHBOARD_HTML_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.mark.unit
def test_main_js_references_editor_theme_storage_key():
    js = _main_js()
    assert ("'qm-editor-theme'" in js) or ('"qm-editor-theme"' in js), (
        "Expected static/main.js to reference the localStorage key "
        "'qm-editor-theme' (as a single- or double-quoted string literal), "
        "mirroring the existing 'qm-density' pattern. This key is needed to "
        "persist the user's explicit editor-theme preference "
        "(follow/light/dark). RED phase: this wiring does not exist yet."
    )


@pytest.mark.unit
def test_main_js_persists_editor_theme_preference():
    js = _main_js()
    assert "localStorage.setItem" in js, (
        "Expected static/main.js to call localStorage.setItem(...) somewhere, "
        "as the mechanism used to persist the editor-theme preference. RED "
        "phase: this wiring does not exist yet."
    )
    assert "qm-editor-theme" in js, (
        "Expected static/main.js to reference the 'qm-editor-theme' key "
        "(used as the localStorage.setItem key when persisting the user's "
        "explicit editor-theme choice). RED phase: this wiring does not "
        "exist yet."
    )


@pytest.mark.unit
def test_main_js_reads_editor_theme_preference():
    js = _main_js()
    assert re.search(r"getItem\(['\"]qm-editor-theme['\"]\)", js), (
        "Expected static/main.js to call "
        "localStorage.getItem('qm-editor-theme') somewhere, as the mechanism "
        "used by applyEditorTheme()/init code to resolve the persisted "
        "editor-theme preference (follow/light/dark). RED phase: this "
        "wiring does not exist yet."
    )


@pytest.mark.unit
def test_dashboard_html_has_editor_theme_radio_group():
    html = _dashboard_html()
    assert re.search(r"<input\s+type=\"radio\"[^>]*name=\"editor_theme\"", html) or re.search(
        r"<input\s+type='radio'[^>]*name=\"editor_theme\"", html
    ), (
        "Expected templates/dashboard.html to contain a "
        "`<input type=\"radio\" ... name=\"editor_theme\" ...>` element, as "
        "part of the new tri-state (follow/light/dark) radio group for the "
        "editor-theme preference, mirroring the existing UI Density radio "
        "group. RED phase: this wiring does not exist yet."
    )
    assert 'value="follow"' in html, (
        "Expected templates/dashboard.html to contain a radio option with "
        'value="follow" for the editor-theme preference group. RED phase: '
        "this wiring does not exist yet."
    )
    assert 'value="light"' in html, (
        "Expected templates/dashboard.html to contain a radio option with "
        'value="light" for the editor-theme preference group. RED phase: '
        "this wiring does not exist yet."
    )
    assert 'value="dark"' in html, (
        "Expected templates/dashboard.html to contain a radio option with "
        'value="dark" for the editor-theme preference group. RED phase: '
        "this wiring does not exist yet."
    )
