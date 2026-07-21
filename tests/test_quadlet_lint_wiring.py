"""
Tests for wiring the client-side quadlet-lint adapter into the editor pane
(Issue #199).

These assert wiring that does not exist yet -- static/quadlet_lint.js is not
loaded by dashboard.html, and templates/partials/editor_pane.html does not
create a Monaco model explicitly, call attachQuadletLint, or dispose of the
model/detach handler on teardown. This is the RED phase of a TDD cycle: all
tests below are expected to fail until that wiring is implemented.
"""
import os
import re

import pytest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
DASHBOARD_HTML_PATH = os.path.join(BASE_DIR, "templates", "dashboard.html")
EDITOR_PANE_HTML_PATH = os.path.join(BASE_DIR, "templates", "partials", "editor_pane.html")


def _dashboard_html():
    with open(DASHBOARD_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _editor_pane_html():
    with open(EDITOR_PANE_HTML_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.mark.unit
def test_dashboard_loads_quadlet_lint_as_module_script():
    html = _dashboard_html()
    match = re.search(
        r'<script[^>]*type="module"[^>]*src="/static/quadlet_lint\.js[^"]*"[^>]*>'
        r'|<script[^>]*src="/static/quadlet_lint\.js[^"]*"[^>]*type="module"[^>]*>',
        html,
    )
    assert match, (
        "Expected dashboard.html to load /static/quadlet_lint.js via "
        '<script type="module" src="/static/quadlet_lint.js">. Without this, the '
        "client-side quadlet-lint adapter is never loaded into the page."
    )


@pytest.mark.unit
def test_editor_pane_creates_model_explicitly():
    html = _editor_pane_html()
    assert "monaco.Uri.file(" in html, (
        "Expected editor_pane.html to build an explicit monaco.Uri.file(...) so the "
        "model's uri.path can drive quadlet-lint's file-type rules. Without an explicit "
        "URI, lintModel() cannot infer the unit type from the filename."
    )
    assert "monaco.editor.createModel(" in html, (
        "Expected editor_pane.html to create the Monaco model explicitly via "
        "monaco.editor.createModel(...) (passed to editor.create via the `model` option), "
        "instead of relying on monaco.editor.create()'s implicit model creation. An "
        "explicit model is required so it can be handed to attachQuadletLint() and "
        "disposed independently of the editor instance."
    )


@pytest.mark.unit
def test_editor_pane_calls_attach_quadlet_lint():
    html = _editor_pane_html()
    assert "attachQuadletLint" in html, (
        "Expected editor_pane.html to call attachQuadletLint(...) to wire live linting "
        "into the newly created editor model. Without this call, quadlet-lint never runs "
        "in the editor."
    )


@pytest.mark.unit
def test_editor_pane_teardown_disposes_previous_model():
    html = _editor_pane_html()

    # Find the teardown block: the `if (window.editor) { ... }` guard that runs
    # before a new pane is created. It must capture the previous model, dispose
    # the editor, and dispose the captured model -- the relative order of the
    # editor.dispose() and model.dispose() calls is not asserted here (disposing
    # the editor first is in fact the safe order, since it detaches the model
    # before the model itself is disposed).
    teardown_match = re.search(
        r"if\s*\(\s*window\.editor\s*\)\s*\{(.*?)\}", html, re.DOTALL
    )
    assert teardown_match, (
        "Expected editor_pane.html to still contain an `if (window.editor) { ... }` "
        "teardown block that disposes the previous editor and model."
    )

    teardown_block = teardown_match.group(1)

    dispose_editor_match = re.search(r"window\.editor\.dispose\(\)", teardown_block)
    assert dispose_editor_match, (
        "Expected the existing window.editor.dispose() teardown call to still be present "
        "in editor_pane.html."
    )

    get_model_match = re.search(r"(\w+)\s*=\s*window\.editor\.getModel\(\)", teardown_block)
    assert get_model_match, (
        "Expected the teardown block to capture the "
        "previous model via window.editor.getModel(), e.g. `var prevModel = "
        "window.editor.getModel();`. editor.dispose() does NOT dispose a model that was "
        "passed in explicitly via the `model` option, so without capturing and disposing "
        "it here, every unit visited in the editor leaks its Monaco model."
    )

    captured_var = get_model_match.group(1)
    dispose_model_pattern = re.escape(captured_var) + r"\s*&&\s*" + re.escape(captured_var) + r"\.dispose\(\)|" \
        + re.escape(captured_var) + r"\.dispose\(\)"
    assert re.search(dispose_model_pattern, teardown_block), (
        f"Expected the teardown block to call {captured_var}.dispose() on the model "
        "captured via getModel(), somewhere in the same `if (window.editor) {{ ... }}` "
        "block. editor.dispose() does NOT dispose a model passed in explicitly via the "
        "`model` option, so without this call, every unit visited in the editor leaks "
        "its Monaco model."
    )


@pytest.mark.unit
def test_editor_pane_teardown_calls_detach_function():
    html = _editor_pane_html()
    assert "window._quadletLintDetach" in html, (
        "Expected editor_pane.html to store the detach() function returned by "
        "attachQuadletLint() on window._quadletLintDetach, and to call it during "
        "teardown (before disposing the previous model/editor). Without calling detach(), "
        "a pending debounced lint from the previous pane can fire against an already-"
        "disposed model."
    )

    dispose_editor_match = re.search(r"window\.editor\.dispose\(\)", html)
    assert dispose_editor_match, "Expected window.editor.dispose() to still be present."
    teardown_block = html[: dispose_editor_match.start()]
    assert "window._quadletLintDetach" in teardown_block and "(" in teardown_block, (
        "Expected window._quadletLintDetach() to be invoked in the teardown block, ahead "
        "of window.editor.dispose(), so a pending debounced lint cannot fire against a "
        "disposed model."
    )


@pytest.mark.unit
def test_editor_pane_does_not_reuse_quadlet_owner_string():
    html = _editor_pane_html()
    assert "attachQuadletLint" in html, (
        "Expected editor_pane.html to call attachQuadletLint(...) so the owner-string "
        "guard below is actually exercised. Without this call, quadlet-lint never runs "
        "in the editor."
    )
    assert "'quadlet'" not in html and '"quadlet"' not in html, (
        "editor_pane.html must not pass the marker owner string 'quadlet' to "
        "attachQuadletLint (or setModelMarkers). That owner string belongs to the "
        "server-validate path at static/main.js:2779 (monaco.editor.setModelMarkers"
        "(window.editor.getModel(), 'quadlet', markers)); sharing it with the client-side "
        "quadlet-lint path would make each run wipe the other's markers via "
        "setModelMarkers' owner-scoped replace semantics. attachQuadletLint should be "
        "called without an owner override so it uses its own 'quadlet-lint' owner."
    )
