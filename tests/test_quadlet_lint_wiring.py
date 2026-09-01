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
QUADLET_LINT_JS_PATH = os.path.join(BASE_DIR, "static", "quadlet_lint.js")
EDITOR_JS_PATH = os.path.join(BASE_DIR, "static", "modules", "editor.js")


def _dashboard_html():
    with open(DASHBOARD_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _editor_pane_html():
    with open(EDITOR_PANE_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _editor_js():
    with open(EDITOR_JS_PATH, encoding="utf-8") as f:
        return f.read()


def _mount_editor_pane_js():
    """Source of editor.js's mountEditorPane(), sliced out of the module.

    The assertions below look for strings such as `'quadlet'` and
    `if (window.editor)` that also occur elsewhere in editor.js, in the
    server-validate path and in initEditor(). Slicing to this one
    function keeps each check aimed at the editor-pane mount it was
    written for.
    """
    with open(EDITOR_JS_PATH, encoding="utf-8") as f:
        source = f.read()
    marker = "export function mountEditorPane("
    start = source.find(marker)
    if start == -1:
        pytest.fail(
            "static/modules/editor.js must export mountEditorPane(); issue #468 "
            "moves the editor pane's inline <script> into that function"
        )
    rest = source[start + len(marker):]
    end = re.search(r"^export\s", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def _quadlet_lint_js():
    with open(QUADLET_LINT_JS_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.mark.unit
def test_dashboard_loads_quadlet_lint_as_module_script():
    html = _dashboard_html()
    match = re.search(
        r'<script[^>]*type="module"[^>]*src="(?:/static/quadlet_lint\.js[^"]*|'
        r'\{\{ *asset_url\(.quadlet_lint\.js.\) *\}\})"[^>]*>'
        r'|<script[^>]*src="(?:/static/quadlet_lint\.js[^"]*|'
        r'\{\{ *asset_url\(.quadlet_lint\.js.\) *\}\})"[^>]*type="module"[^>]*>',
        html,
    )
    assert match, (
        "Expected dashboard.html to load quadlet_lint.js via a "
        '<script type="module"> tag, either with a literal /static/ path or '
        "through asset_url(). Without this, the "
        "client-side quadlet-lint adapter is never loaded into the page."
    )


@pytest.mark.unit
def test_editor_pane_creates_model_explicitly():
    html = _mount_editor_pane_js()
    assert "monaco.Uri.file(" in html, (
        "Expected mountEditorPane() to build an explicit monaco.Uri.file(...) so the "
        "model's uri.path can drive quadlet-lint's file-type rules. Without an explicit "
        "URI, lintModel() cannot infer the unit type from the filename."
    )
    assert "monaco.editor.createModel(" in html, (
        "Expected mountEditorPane() to create the Monaco model explicitly via "
        "monaco.editor.createModel(...) (passed to editor.create via the `model` option), "
        "instead of relying on monaco.editor.create()'s implicit model creation. An "
        "explicit model is required so it can be handed to attachQuadletLint() and "
        "disposed independently of the editor instance."
    )


@pytest.mark.unit
def test_editor_pane_calls_attach_quadlet_lint():
    html = _mount_editor_pane_js()
    assert "attachQuadletLint" in html, (
        "Expected mountEditorPane() to call attachQuadletLint(...) to wire live linting "
        "into the newly created editor model. Without this call, quadlet-lint never runs "
        "in the editor."
    )


@pytest.mark.unit
def test_editor_pane_teardown_disposes_previous_model():
    html = _mount_editor_pane_js()

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
        "Expected mountEditorPane() to still contain an `if (window.editor) { ... }` "
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
    html = _mount_editor_pane_js()
    assert "window._quadletLintDetach" in html, (
        "Expected mountEditorPane() to store the detach() function returned by "
        "attachQuadletLint() on window._quadletLintDetach, and to call it during "
        "teardown (before disposing the previous model/editor). Without calling detach(), "
        "a pending debounced lint from the previous pane can fire against an already-"
        "disposed model."
    )

    dispose_editor_match = re.search(r"window\.editor\.dispose\(\)", html)
    assert dispose_editor_match, "Expected window.editor.dispose() to still be present."
    teardown_block = html[: dispose_editor_match.start()]
    assert "window._quadletLintDetach(" in teardown_block, (
        "Expected window._quadletLintDetach() to be invoked in the teardown block, ahead "
        "of window.editor.dispose(), so a pending debounced lint cannot fire against a "
        "disposed model."
    )


@pytest.mark.unit
def test_editor_pane_does_not_reuse_quadlet_owner_string():
    html = _mount_editor_pane_js()
    assert "attachQuadletLint" in html, (
        "Expected mountEditorPane() to call attachQuadletLint(...) so the owner-string "
        "guard below is actually exercised. Without this call, quadlet-lint never runs "
        "in the editor."
    )
    assert "'quadlet'" not in html, (
        "mountEditorPane() must not pass the marker owner string 'quadlet' to "
        "attachQuadletLint (or setModelMarkers). That owner string belongs to the "
        "server-validate path at static/main.js:2779 (monaco.editor.setModelMarkers"
        "(window.editor.getModel(), 'quadlet', markers)); sharing it with the client-side "
        "quadlet-lint path would make each run wipe the other's markers via "
        "setModelMarkers' owner-scoped replace semantics. attachQuadletLint should be "
        "called without an owner override so it uses its own 'quadlet-lint' owner."
    )
    assert '"quadlet"' not in html, (
        "mountEditorPane() must not pass the marker owner string 'quadlet' to "
        "attachQuadletLint (or setModelMarkers). That owner string belongs to the "
        "server-validate path at static/main.js:2779 (monaco.editor.setModelMarkers"
        "(window.editor.getModel(), 'quadlet', markers)); sharing it with the client-side "
        "quadlet-lint path would make each run wipe the other's markers via "
        "setModelMarkers' owner-scoped replace semantics. attachQuadletLint should be "
        "called without an owner override so it uses its own 'quadlet-lint' owner."
    )


@pytest.mark.unit
def test_quadlet_lint_js_defines_register_providers_helper():
    js = _quadlet_lint_js()

    assert "registerCompletionProvider" in js, (
        "Expected static/quadlet_lint.js to import registerCompletionProvider from "
        "./vendor/quadlet-lint/monaco.js. Without this import, quadlet_lint.js has no "
        "way to wire Monaco completion suggestions into the editor."
    )
    assert "registerHoverProvider" in js, (
        "Expected static/quadlet_lint.js to import registerHoverProvider from "
        "./vendor/quadlet-lint/monaco.js. Without this import, quadlet_lint.js has no "
        "way to wire Monaco hover tooltips into the editor."
    )
    assert "registerCodeActionProvider" in js, (
        "Expected static/quadlet_lint.js to import registerCodeActionProvider from "
        "./vendor/quadlet-lint/monaco.js. Without this import, quadlet_lint.js has no "
        "way to wire Monaco quick-fix code actions into the editor."
    )
    assert "registerQuadletLintProviders" in js, (
        "Expected static/quadlet_lint.js to define and export a "
        "registerQuadletLintProviders(monacoNs, languageId) function that registers all "
        "three quadlet-lint Monaco providers. Without this exported helper, callers have "
        "no single entry point to wire completion/hover/code-action support into a "
        "Monaco language."
    )
    assert "registerCompletionProvider(" in js, (
        "Expected static/quadlet_lint.js's registerQuadletLintProviders() to actually "
        "call registerCompletionProvider(...), not just import it."
    )
    assert "registerHoverProvider(" in js, (
        "Expected static/quadlet_lint.js's registerQuadletLintProviders() to actually "
        "call registerHoverProvider(...), not just import it."
    )
    assert "registerCodeActionProvider(" in js, (
        "Expected static/quadlet_lint.js's registerQuadletLintProviders() to actually "
        "call registerCodeActionProvider(...), not just import it."
    )


@pytest.mark.unit
def test_editor_pane_registers_providers_once_behind_guard():
    html = _mount_editor_pane_js()
    assert "registerQuadletLintProviders(" in html, (
        "Expected mountEditorPane() to call registerQuadletLintProviders(...) so that "
        "Monaco completion/hover/code-action support for quadlet-lint is actually "
        "registered against the editor's language."
    )
    assert "window._quadletProvidersRegistered" in html, (
        "Expected mountEditorPane() to guard the registerQuadletLintProviders(...) call "
        "with a window._quadletProvidersRegistered boolean flag, so the providers are "
        "registered only once no matter how many times the editor pane is (re)created."
    )


@pytest.mark.unit
def test_editor_pane_registers_providers_before_liveness_guard():
    html = _mount_editor_pane_js()

    registration_index = html.find("registerQuadletLintProviders(")
    guard_index = html.find("document.body.contains(targetContainer)")

    assert registration_index != -1, (
        "Expected mountEditorPane() to call registerQuadletLintProviders(...) inside the "
        "require() callback."
    )
    assert guard_index != -1, (
        "Expected mountEditorPane() to still contain the "
        "document.body.contains(targetContainer) liveness guard."
    )
    assert registration_index < guard_index, (
        "Expected registerQuadletLintProviders(...) to run BEFORE the "
        "document.body.contains(targetContainer) liveness early-return in the require() "
        "callback. Provider registration must not be gated behind the per-pane liveness "
        "early-returns, or a fast first-pane swap can permanently skip global provider "
        "registration entirely."
    )


@pytest.mark.unit
def test_dashboard_has_no_inline_module_script():
    html = _dashboard_html()
    inline_module_tags = [
        m.group(0)
        for m in re.finditer(r"<script\b([^>]*)>", html, re.IGNORECASE)
        if re.search(r'\btype=["\']module["\']', m.group(1), re.IGNORECASE)
        and not re.search(r'\bsrc\s*=', m.group(1), re.IGNORECASE)
    ]
    assert not inline_module_tags, (
        "Expected dashboard.html to contain no inline <script type=\"module\"> blocks "
        f"without a src attribute, but found: {inline_module_tags}. Issue #472 eliminates "
        "inline module scripts so 'unsafe-inline' can be removed from the script-src CSP."
    )


@pytest.mark.unit
def test_import_map_exposes_quadlet_lint():
    from api.routes import asset_url, module_import_map

    assert (
        module_import_map()["imports"].get("@qm/quadlet_lint")
        == asset_url("quadlet_lint.js")
    ), (
        'Expected module_import_map()["imports"]["@qm/quadlet_lint"] to equal '
        f'{asset_url("quadlet_lint.js")!r} so ES modules can import "@qm/quadlet_lint" '
        f'directly, but got {module_import_map()["imports"].get("@qm/quadlet_lint")!r}.'
    )


@pytest.mark.unit
def test_editor_imports_quadlet_lint_helpers():
    js = _editor_js()
    match = re.search(
        r"import\s*\{(?=[^}]*\battachQuadletLint\b)(?=[^}]*\bregisterQuadletLintProviders\b)[^}]*\}\s*from\s*['\"]@qm/quadlet_lint['\"]",
        js,
    )
    assert match, (
        "Expected static/modules/editor.js to contain a static import statement pulling "
        "both `attachQuadletLint` and `registerQuadletLintProviders` from '@qm/quadlet_lint'."
    )


@pytest.mark.unit
def test_no_static_js_reads_quadlet_lint_globals():
    from tests.js_source import read_static_js

    js = read_static_js()
    forbidden = (
        "window.attachQuadletLint",
        "window.registerQuadletLintProviders",
        "window._quadletLintReady",
    )
    found = [name for name in forbidden if name in js]
    assert not found, (
        "Expected no static JavaScript to read quadlet-lint globals on window, "
        f"but found references to: {found}. Issue #472 removes window globals in favor "
        "of direct ES module imports from '@qm/quadlet_lint'."
    )

