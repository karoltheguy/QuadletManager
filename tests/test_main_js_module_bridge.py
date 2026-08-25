"""Tests for loading static JS as an ES module behind a window bridge (issue #390).

These tests specify the upcoming migration where static scripts are loaded as ES modules
behind a single explicit `Object.assign(window, { ... })` bridge, and the Playwright
e2e readiness gate transitions from `window.runningContainersBySid` to `appReady`.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

from tests.js_source import read_static_js, static_js_files

REPO_ROOT = pathlib.Path(__file__).parent.parent

# JavaScript builtins and standard DOM API identifiers to exclude from template handler checks
BUILTIN_IDENTIFIERS = {
    "document",
    "window",
    "JSON",
    "Object",
    "Array",
    "String",
    "Number",
    "Boolean",
    "Math",
    "console",
    "event",
    "htmx",
    "fetch",
    "alert",
    "confirm",
    "setTimeout",
    "parseInt",
    "parseFloat",
    "encodeURIComponent",
    "getElementById",
    "querySelector",
    "querySelectorAll",
    "closest",
    "remove",
    "matchMedia",
    "function",
    "catch",
    "if",
    "return",
    "typeof",
}

# Names owned by other modules, not the main script bundle:
# - attachQuadletLint and registerQuadletLintProviders come from static/quadlet_lint.js
# - editor, _editorDirty, _quadletLintDetach, _quadletLintReady and _quadletProvidersRegistered
#   are owned by templates/partials/editor_pane.html
OTHER_MODULE_IDENTIFIERS = {
    "attachQuadletLint",
    "registerQuadletLintProviders",
    "editor",
    "_editorDirty",
    "_quadletLintDetach",
    "_quadletLintReady",
    "_quadletProvidersRegistered",
}


@pytest.mark.unit
def test_dashboard_loads_main_js_as_a_module():
    """Verify that templates/dashboard.html loads main.js with type="module"."""
    dashboard_path = REPO_ROOT / "templates" / "dashboard.html"
    content = dashboard_path.read_text(encoding="utf-8")

    script_pattern = re.compile(r"<script\b([^>]*)>", re.IGNORECASE)
    matching_tags = [
        tag for tag in script_pattern.findall(content)
        if "asset_url('main.js')" in tag or 'asset_url("main.js")' in tag
    ]
    assert matching_tags, "No <script> tag referencing asset_url('main.js') found in templates/dashboard.html"
    for tag_attrs in matching_tags:
        assert re.search(r'type=["\']module["\']', tag_attrs), (
            f'Expected <script> tag for main.js to have type="module", got: <script{tag_attrs}>'
        )


@pytest.mark.unit
def test_main_js_has_exactly_one_window_bridge():
    """Verify that JS sources have exactly one Object.assign(window, { ... }) bridge and no loose window assignments."""
    content = read_static_js()
    bridge_occurrences = content.count("Object.assign(window, {")
    assert bridge_occurrences == 1, (
        f"Expected exactly 1 'Object.assign(window, {{' bridge block, found {bridge_occurrences}"
    )

    # Only top-level statements count, so this anchors at column 0 with no
    # leading whitespace. Every function body in these files is indented, and an
    # indented `window.foo = bar` is a mutation of an already bridged global, not
    # a second bridge. Also catches the `const x = window.x = ...` form, e.g.
    # `const runningContainersBySid = window.runningContainersBySid = {};`.
    outside_bridge = re.sub(
        r"Object\.assign\s*\(\s*window\s*,\s*\{.*?\}\s*\)\s*;",
        "",
        content,
        flags=re.DOTALL,
    )
    top_level_assignments = re.findall(
        r"^(?:(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*)?"
        r"window\.([A-Za-z_$][\w$]*)\s*=(?!=)",
        outside_bridge,
        re.MULTILINE,
    )
    assert not top_level_assignments, (
        f"Found top-level window assignments outside bridge: {sorted(set(top_level_assignments))}"
    )


@pytest.mark.unit
def test_every_template_inline_handler_is_on_the_bridge():
    """Verify all inline event handlers and window refs across templates are exposed on the window bridge."""
    templates_dir = REPO_ROOT / "templates"

    inline_handler_attr_pattern = re.compile(r'\bon[a-z]+\s*=\s*(["\'])(.*?)\1', re.IGNORECASE | re.DOTALL)
    call_target_pattern = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
    window_ref_pattern = re.compile(r"\bwindow\.([A-Za-z_$][\w$]*)\b")
    script_block_pattern = re.compile(r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
    script_func_pattern = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\b")

    used_names = set()
    template_script_funcs = set()

    for html_file in templates_dir.rglob("*.html"):
        content = html_file.read_text(encoding="utf-8")

        # Collect functions declared in template script blocks
        for script_match in script_block_pattern.findall(content):
            for func in script_func_pattern.findall(script_match):
                template_script_funcs.add(func)

        # Collect call targets and window.NAME references in inline event handlers
        for _, handler_code in inline_handler_attr_pattern.findall(content):
            for call_target in call_target_pattern.findall(handler_code):
                used_names.add(call_target)
            for win_ref in window_ref_pattern.findall(handler_code):
                used_names.add(win_ref)

        # Collect window.NAME references anywhere else in the template
        for win_ref in window_ref_pattern.findall(content):
            used_names.add(win_ref)

    surviving_names = used_names - BUILTIN_IDENTIFIERS - template_script_funcs - OTHER_MODULE_IDENTIFIERS

    # Extract keys exposed in the Object.assign(window, { ... }) bridge block
    js_source = read_static_js()
    bridge_match = re.search(r"Object\.assign\s*\(\s*window\s*,\s*\{(.*?)\}\s*\)", js_source, re.DOTALL)
    if bridge_match:
        bridge_body = bridge_match.group(1)
        bridge_keys = set(re.findall(r"\b([A-Za-z_$][\w$]*)\b", bridge_body))
    else:
        bridge_keys = set()

    missing = sorted(surviving_names - bridge_keys)
    assert not missing, (
        f"Missing template handlers/globals from window bridge ({len(missing)}): {missing}"
    )


@pytest.mark.unit
def test_e2e_readiness_uses_an_explicit_app_ready_flag():
    """Verify that e2e tests and documentation use the explicit dataset.appReady readiness flag."""
    js_source = read_static_js()
    assert "document.documentElement.dataset.appReady = '1'" in js_source, (
        "JS source must set document.documentElement.dataset.appReady = '1'"
    )

    conftest_path = REPO_ROOT / "tests" / "e2e" / "conftest.py"
    conftest_content = conftest_path.read_text(encoding="utf-8")
    assert "appReady" in conftest_content, (
        "tests/e2e/conftest.py must wait on appReady"
    )
    assert "runningContainersBySid" not in conftest_content, (
        "tests/e2e/conftest.py must no longer reference runningContainersBySid"
    )

    agents_md_path = REPO_ROOT / "AGENTS.MD"
    agents_md_content = agents_md_path.read_text(encoding="utf-8")
    assert "appReady" in agents_md_content, (
        "AGENTS.MD must document appReady"
    )
    assert "runningContainersBySid" not in agents_md_content, (
        "AGENTS.MD must no longer reference runningContainersBySid"
    )


@pytest.mark.unit
def test_static_js_sources_are_syntactically_valid():
    """Parse every non-vendor static JS file with node.

    The rest of this suite asserts on JS as text, so a file can be malformed
    JavaScript and still pass every structural test while the browser refuses to
    execute it. This is the only check that actually parses the source.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    for path in static_js_files():
        result = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"{path.name} is not valid JavaScript:\n{result.stderr}"
        )
