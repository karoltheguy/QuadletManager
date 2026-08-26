"""Tests for delegated event handlers (issue #392).

These tests specify replacing inline onclick handlers in templates with data-action
attributes and a delegated document click listener, allowing corresponding function
names to be removed from the window bridge.
"""
import ast
import pathlib
import re

import pytest

from tests.js_source import read_static_js

REPO_ROOT = pathlib.Path(__file__).parent.parent

# Each #392 group appends its retired function names here.
RETIRED_BRIDGE_NAMES = frozenset({
    # group 1 (#401): top nav and settings sidenav
    "switchTab",
    "showSettingsSection",
    # group 2 (#404): bottom panel controls
    "switchBottomTab",
    "connectTerminal",
    "tailLogsFromPanel",
    "toggleBottomPanelExpand",
    "toggleBottomPanel",
    "sessionAddNew",
    "disconnectTerminal",
    # group 3 (#392): monitor pane controls
    "selectMonitoringServer",
    "applyContainerFilter",
    "loadMonitorCharts",
    # group 4 (#412): editor pane actions
    "validateQuadlet",
    "saveQuadlet",
    "toggleInspectorExpand",
    # group 5 (#414): top nav leftovers
    "toggleTheme",
    "toggleProfileMenu",
    "softRefresh",
    # group 6 (#416): appearance radios
    "toggleDensity",
    "toggleEditorTheme",
    # group 7 (#418): theme customization controls
    "applyThemePreview",
    "clearThemePreview",
})


@pytest.mark.unit
def test_retired_names_are_not_inline_handlers():
    """Verify that templates do not use inline event handlers for retired bridge names."""
    templates_dir = REPO_ROOT / "templates"
    inline_handler_attr_pattern = re.compile(
        r'\bon[a-z]+\s*=\s*(["\'])(.*?)\1', re.IGNORECASE | re.DOTALL
    )

    violations = []
    for html_file in templates_dir.rglob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        for _, handler_code in inline_handler_attr_pattern.findall(content):
            for target in sorted(RETIRED_BRIDGE_NAMES):
                if target in handler_code:
                    rel_path = html_file.relative_to(REPO_ROOT)
                    violations.append(f"{rel_path}: inline handler mentions {target}")

    assert not violations, (
        f"Found inline handlers for retired names in templates ({len(violations)}):\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


@pytest.mark.unit
def test_retired_names_are_off_the_window_bridge():
    """Verify that retired names are removed from the window bridge."""
    js_source = read_static_js()
    bridge_match = re.search(
        r"Object\.assign\s*\(\s*window\s*,\s*\{(.*?)\}\s*\)",
        js_source,
        re.DOTALL,
    )
    assert bridge_match, "Could not find Object.assign(window, { ... }) bridge block in JS source"
    bridge_body = bridge_match.group(1)
    bridge_keys = set(re.findall(r"\b([A-Za-z_$][\w$]*)\b", bridge_body))

    forbidden_keys = RETIRED_BRIDGE_NAMES
    exposed_forbidden = sorted(bridge_keys & forbidden_keys)
    assert not exposed_forbidden, (
        f"Expected retired names to be removed from window bridge, but found: {exposed_forbidden}"
    )


@pytest.mark.unit
def test_nav_buttons_declare_delegated_actions():
    """Verify that nav and settings buttons declare data-action and target identifiers."""
    dashboard_path = REPO_ROOT / "templates" / "dashboard.html"
    content = dashboard_path.read_text(encoding="utf-8")

    button_pattern = re.compile(r"<button\b([^>]*)>", re.IGNORECASE)
    all_buttons = button_pattern.findall(content)

    nav_buttons = [
        attrs for attrs in all_buttons
        if re.search(r'\bclass=["\'][^"\']*\bnav-item\b[^"\']*["\']', attrs)
    ]
    settings_buttons = [
        attrs for attrs in all_buttons
        if re.search(r'\bclass=["\'][^"\']*\bsettings-sidenav-item\b[^"\']*["\']', attrs)
    ]

    assert nav_buttons, "No nav-item buttons found in templates/dashboard.html"
    assert settings_buttons, "No settings-sidenav-item buttons found in templates/dashboard.html"

    nav_tabs = []
    for attrs in nav_buttons:
        action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
        assert action_match, (
            f'Expected nav-item button to have a data-action attribute, got: <button{attrs}>'
        )
        assert action_match.group(1) == "switch-tab", (
            f'Expected nav-item button to have data-action="switch-tab", got: <button{attrs}>'
        )
        tab_match = re.search(r'\bdata-tab=["\']([^"\']+)["\']', attrs)
        assert tab_match, (
            f'Expected nav-item button to have a data-tab attribute, got: <button{attrs}>'
        )
        assert tab_match.group(1).strip(), (
            f'Expected nav-item button to have a non-empty data-tab attribute, got: <button{attrs}>'
        )
        nav_tabs.append(tab_match.group(1).strip())

    expected_tabs = ["overview", "monitor", "containers", "settings"]
    assert nav_tabs == expected_tabs, (
        f"Expected nav-item data-tab values to be {expected_tabs}, got: {nav_tabs}"
    )

    settings_sections = []
    for attrs in settings_buttons:
        action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
        assert action_match, (
            f'Expected settings-sidenav-item button to have a data-action attribute, got: <button{attrs}>'
        )
        assert action_match.group(1) == "show-settings-section", (
            f'Expected settings-sidenav-item button to have data-action="show-settings-section", got: <button{attrs}>'
        )
        section_match = re.search(r'\bdata-section=["\']([^"\']+)["\']', attrs)
        assert section_match, (
            f'Expected settings-sidenav-item button to have a data-section attribute, got: <button{attrs}>'
        )
        assert section_match.group(1).strip(), (
            f'Expected settings-sidenav-item button to have a non-empty data-section attribute, got: <button{attrs}>'
        )
        settings_sections.append(section_match.group(1).strip())

    expected_sections = ["servers", "ssh-keys", "users", "themes", "admin"]
    assert settings_sections == expected_sections, (
        f"Expected settings-sidenav-item data-section values to be {expected_sections}, got: {settings_sections}"
    )


@pytest.mark.unit
def test_bottom_panel_buttons_declare_delegated_actions():
    """Verify that bottom panel buttons declare data-action and target identifiers."""
    dashboard_path = REPO_ROOT / "templates" / "dashboard.html"
    content = dashboard_path.read_text(encoding="utf-8")

    button_pattern = re.compile(r"<button\b([^>]*)>", re.IGNORECASE)
    all_buttons = button_pattern.findall(content)

    bottom_tab_buttons = [
        attrs for attrs in all_buttons
        if re.search(r'\bclass=["\'][^"\']*\bbottom-tab\b[^"\']*["\']', attrs)
    ]

    assert bottom_tab_buttons, "No bottom-tab buttons found in templates/dashboard.html"
    assert len(bottom_tab_buttons) == 2, (
        f"Expected 2 bottom-tab buttons in templates/dashboard.html, found {len(bottom_tab_buttons)}"
    )

    bottom_panes = []
    for attrs in bottom_tab_buttons:
        action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
        assert action_match, (
            f'Expected bottom-tab button to have a data-action attribute, got: <button{attrs}>'
        )
        assert action_match.group(1) == "switch-bottom-tab", (
            f'Expected bottom-tab button to have data-action="switch-bottom-tab", got: <button{attrs}>'
        )
        pane_match = re.search(r'\bdata-pane=["\']([^"\']+)["\']', attrs)
        assert pane_match, (
            f'Expected bottom-tab button to have a data-pane attribute, got: <button{attrs}>'
        )
        assert pane_match.group(1).strip(), (
            f'Expected bottom-tab button to have a non-empty data-pane attribute, got: <button{attrs}>'
        )
        bottom_panes.append(pane_match.group(1).strip())

    expected_panes = ["terminal", "logs"]
    assert bottom_panes == expected_panes, (
        f"Expected bottom-tab data-pane values to be {expected_panes}, got: {bottom_panes}"
    )

    expected_id_actions = {
        "terminal-connect-btn": "connect-terminal",
        "toggle-logs-btn": "tail-logs",
        "bottom-panel-expand-btn": "toggle-bottom-panel-expand",
        "bottom-panel-minimize-btn": "toggle-bottom-panel",
        "session-add-btn": "session-add-new",
    }

    for btn_id, expected_action in expected_id_actions.items():
        matching = [
            attrs for attrs in all_buttons
            if re.search(rf'\bid=["\']{re.escape(btn_id)}["\']', attrs)
        ]
        assert matching, (
            f"Expected button with id='{btn_id}' in templates/dashboard.html"
        )
        assert len(matching) == 1, (
            f"Expected exactly 1 button with id='{btn_id}' in templates/dashboard.html, found {len(matching)}"
        )
        attrs = matching[0]
        action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
        assert action_match, (
            f"Expected button #{btn_id} to have a data-action attribute, got: <button{attrs}>"
        )
        assert action_match.group(1) == expected_action, (
            f"Expected button #{btn_id} to have data-action='{expected_action}', got: <button{attrs}>"
        )


@pytest.mark.unit
def test_monitor_controls_declare_delegated_actions():
    """Verify that monitor pane controls declare data-action and target identifiers."""
    dashboard_path = REPO_ROOT / "templates" / "dashboard.html"
    content = dashboard_path.read_text(encoding="utf-8")

    select_pattern = re.compile(
        r'<select\b[^>]*\bid=["\']monitoring-server-select["\'][^>]*>', re.IGNORECASE
    )
    select_match = select_pattern.search(content)
    assert select_match, (
        "Expected <select id=\"monitoring-server-select\"> in templates/dashboard.html"
    )
    select_attrs = select_match.group(0)
    action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', select_attrs)
    assert action_match, (
        f"Expected #monitoring-server-select to have a data-action attribute, got: {select_attrs}"
    )
    assert action_match.group(1) == "select-monitoring-server", (
        f"Expected #monitoring-server-select to have data-action='select-monitoring-server', got: {select_attrs}"
    )

    input_pattern = re.compile(
        r'<input\b[^>]*\bid=["\']monitor-container-filter["\'][^>]*>', re.IGNORECASE
    )
    input_match = input_pattern.search(content)
    assert input_match, (
        "Expected <input id=\"monitor-container-filter\"> in templates/dashboard.html"
    )
    input_attrs = input_match.group(0)
    action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', input_attrs)
    assert action_match, (
        f"Expected #monitor-container-filter to have a data-action attribute, got: {input_attrs}"
    )
    assert action_match.group(1) == "filter-monitor-containers", (
        f"Expected #monitor-container-filter to have data-action='filter-monitor-containers', got: {input_attrs}"
    )

    button_pattern = re.compile(r"<button\b([^>]*)>", re.IGNORECASE)
    all_buttons = button_pattern.findall(content)

    health_range_buttons = [
        attrs for attrs in all_buttons
        if re.search(r'\bclass=["\'][^"\']*\bhealth-range-btn\b[^"\']*["\']', attrs)
    ]

    assert health_range_buttons, "No health-range-btn buttons found in templates/dashboard.html"
    assert len(health_range_buttons) == 4, (
        f"Expected 4 health-range-btn buttons in templates/dashboard.html, found {len(health_range_buttons)}"
    )

    minutes_values = []
    for attrs in health_range_buttons:
        action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
        assert action_match, (
            f'Expected health-range-btn button to have a data-action attribute, got: <button{attrs}>'
        )
        assert action_match.group(1) == "load-monitor-charts", (
            f'Expected health-range-btn button to have data-action="load-monitor-charts", got: <button{attrs}>'
        )
        minutes_match = re.search(r'\bdata-minutes=["\']([^"\']+)["\']', attrs)
        assert minutes_match, (
            f'Expected health-range-btn button to have a data-minutes attribute, got: <button{attrs}>'
        )
        minutes_values.append(minutes_match.group(1).strip())

    expected_minutes = ["60", "360", "1440", "10080"]
    assert minutes_values == expected_minutes, (
        f"Expected health-range-btn data-minutes values to be {expected_minutes}, got: {minutes_values}"
    )


@pytest.mark.unit
def test_editor_pane_buttons_declare_delegated_actions():
    """Verify that editor pane buttons declare the expected data-action attribute."""
    button_pattern = re.compile(r"<button\b([^>]*)>", re.IGNORECASE)

    expected_id_actions = {
        "validate-btn": "validate-quadlet",
        "save-btn": "save-quadlet",
        "inspector-expand-btn": "toggle-inspector-expand",
    }

    for template_name in ("templates/partials/editor_pane.html", "templates/dashboard.html"):
        template_path = REPO_ROOT / template_name
        content = template_path.read_text(encoding="utf-8")
        all_buttons = button_pattern.findall(content)

        ids_to_check = expected_id_actions if template_name == "templates/partials/editor_pane.html" else {
            "inspector-expand-btn": expected_id_actions["inspector-expand-btn"],
        }

        for btn_id, expected_action in ids_to_check.items():
            matching = [
                attrs for attrs in all_buttons
                if re.search(rf'\bid=["\']{re.escape(btn_id)}["\']', attrs)
            ]
            assert matching, (
                f"Expected button with id='{btn_id}' in {template_name}"
            )
            assert len(matching) == 1, (
                f"Expected exactly 1 button with id='{btn_id}' in {template_name}, found {len(matching)}"
            )
            attrs = matching[0]
            action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
            assert action_match, (
                f"Expected button #{btn_id} in {template_name} to have a data-action attribute, got: <button{attrs}>"
            )
            assert action_match.group(1) == expected_action, (
                f"Expected button #{btn_id} in {template_name} to have data-action='{expected_action}', got: <button{attrs}>"
            )


@pytest.mark.unit
def test_top_nav_leftover_buttons_declare_delegated_actions():
    """Verify that top nav leftover controls declare the expected data-action attribute."""
    dashboard_path = REPO_ROOT / "templates" / "dashboard.html"
    content = dashboard_path.read_text(encoding="utf-8")

    button_pattern = re.compile(r"<button\b([^>]*)>", re.IGNORECASE)
    all_buttons = button_pattern.findall(content)

    theme_toggle_buttons = [
        attrs for attrs in all_buttons
        if re.search(r'\bclass=["\'][^"\']*\btheme-toggle\b[^"\']*["\']', attrs)
    ]
    assert theme_toggle_buttons, "No theme-toggle buttons found in templates/dashboard.html"
    assert len(theme_toggle_buttons) == 1, (
        f"Expected 1 theme-toggle button in templates/dashboard.html, found {len(theme_toggle_buttons)}"
    )
    attrs = theme_toggle_buttons[0]
    action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
    assert action_match, (
        f'Expected theme-toggle button to have a data-action attribute, got: <button{attrs}>'
    )
    assert action_match.group(1) == "toggle-theme", (
        f'Expected theme-toggle button to have data-action="toggle-theme", got: <button{attrs}>'
    )

    profile_btn_matches = [
        attrs for attrs in all_buttons
        if re.search(r'\bid=["\']profile-btn["\']', attrs)
    ]
    assert profile_btn_matches, "Expected button with id='profile-btn' in templates/dashboard.html"
    assert len(profile_btn_matches) == 1, (
        f"Expected exactly 1 button with id='profile-btn' in templates/dashboard.html, found {len(profile_btn_matches)}"
    )
    attrs = profile_btn_matches[0]
    action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
    assert action_match, (
        f"Expected button #profile-btn to have a data-action attribute, got: <button{attrs}>"
    )
    assert action_match.group(1) == "toggle-profile-menu", (
        f"Expected button #profile-btn to have data-action='toggle-profile-menu', got: <button{attrs}>"
    )

    panel_reload_buttons = [
        attrs for attrs in all_buttons
        if re.search(r'\bclass=["\'][^"\']*\bpanel-reload-btn\b[^"\']*["\']', attrs)
    ]
    assert panel_reload_buttons, "No panel-reload-btn buttons found in templates/dashboard.html"
    assert len(panel_reload_buttons) == 1, (
        f"Expected 1 panel-reload-btn button in templates/dashboard.html, found {len(panel_reload_buttons)}"
    )
    attrs = panel_reload_buttons[0]
    action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
    assert action_match, (
        f'Expected panel-reload-btn button to have a data-action attribute, got: <button{attrs}>'
    )
    assert action_match.group(1) == "soft-refresh", (
        f'Expected panel-reload-btn button to have data-action="soft-refresh", got: <button{attrs}>'
    )


@pytest.mark.unit
def test_profile_menu_close_listener_ignores_the_profile_button():
    """Verify the document click listener that hides #profile-menu excludes #profile-btn.

    `stopPropagation` in the button's own click handler does not stop sibling
    listeners bound to the same node (or its ancestors) that were registered
    independently, such as a document-level listener. So the click that opens
    the menu also reaches the document listener that hides it, unless that
    listener explicitly excludes clicks that originated on profile-btn.
    """
    js_source = read_static_js()

    listener_match = re.search(
        r"document\.addEventListener\(\s*'click'\s*,\s*function\s*\([^)]*\)\s*\{"
        r"(?:[^{}]|\{[^{}]*\})*?profile-menu(?:[^{}]|\{[^{}]*\})*?\}\s*\)",
        js_source,
    )
    assert listener_match, (
        "Could not find the document click listener that hides #profile-menu in JS source"
    )
    listener_body = listener_match.group(0)

    assert "profile-btn" in listener_body, (
        "Expected the document click listener that hides #profile-menu to also reference "
        "profile-btn, so it can exclude clicks on the button itself; stopPropagation in "
        "the button's own handler does not stop this independently-registered listener, "
        "so without an explicit exclusion the very click that opens the menu immediately "
        "closes it again. Listener body: " + listener_body
    )


@pytest.mark.unit
def test_js_dispatches_every_delegated_action():
    """Verify that static JS contains delegated action handlers and a click listener."""
    js_source = read_static_js()

    expected_actions = [
        "switch-tab",
        "show-settings-section",
        "switch-bottom-tab",
        "connect-terminal",
        "tail-logs",
        "toggle-bottom-panel-expand",
        "toggle-bottom-panel",
        "session-add-new",
        "select-monitoring-server",
        "filter-monitor-containers",
        "load-monitor-charts",
    ]
    for action in expected_actions:
        # Quoted, so that 'toggle-bottom-panel' is not satisfied by the
        # 'toggle-bottom-panel-expand' key that contains it as a substring.
        assert f"'{action}'" in js_source, (
            f"Expected '{action}' as a quoted action name in static JS source"
        )
    assert "document.addEventListener('click'" in js_source, (
        "Expected static JS to register a document-level click listener with document.addEventListener('click'"
    )
    assert "document.addEventListener('change'" in js_source, (
        "Expected static JS to register a document-level change listener with document.addEventListener('change'"
    )
    assert "document.addEventListener('input'" in js_source, (
        "Expected static JS to register a document-level input listener with document.addEventListener('input'"
    )


@pytest.mark.unit
def test_internal_window_calls_stay_on_the_bridge():
    """Verify no JS source reaches a module-local function through the window bridge.

    Retiring a bridge name (issue #392) is only safe if nothing inside the module
    calls it as `window.NAME`. An ES module's top-level functions are not on
    `window`, so such a call resolves to undefined and throws at runtime. The unit
    suite cannot see that; it took a full e2e run to catch it once already.
    """
    js_source = read_static_js()

    declared = set(re.findall(r"^function\s+([A-Za-z_$][\w$]*)\s*\(", js_source, re.MULTILINE))
    referenced = set(re.findall(r"\bwindow\.([A-Za-z_$][\w$]*)\b", js_source))

    bridge_match = re.search(
        r"Object\.assign\s*\(\s*window\s*,\s*\{(.*?)\}\s*\)",
        js_source,
        re.DOTALL,
    )
    assert bridge_match, "Could not find Object.assign(window, { ... }) bridge block in JS source"
    bridge_keys = set(re.findall(r"\b([A-Za-z_$][\w$]*)\b", bridge_match.group(1)))

    unbridged = sorted((declared & referenced) - bridge_keys)
    assert not unbridged, (
        "These functions are declared in the module but reached through window.NAME "
        f"while absent from the bridge, so the call resolves to undefined: {unbridged}"
    )


@pytest.mark.unit
def test_retired_names_are_not_reached_from_e2e_tests():
    """Verify no e2e test calls a retired name from a page.evaluate string.

    `tests/e2e/` is the third consumer of the bridge, after templates and
    `main.js` itself, and the easiest to forget: a `page.evaluate("someName()")`
    resolves against `window` exactly like an inline handler did. Catching it
    here costs a second; catching it in the browser costs a full e2e run.

    Only executable string literals count. A docstring naming a function is
    prose, not a call, so docstrings are excluded rather than reported.
    """
    e2e_dir = REPO_ROOT / "tests" / "e2e"

    violations = []
    for py_file in sorted(e2e_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))

        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = node.body[0] if node.body else None
                if isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant):
                    docstrings.add(id(doc.value))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str) or id(node) in docstrings:
                continue
            for name in sorted(RETIRED_BRIDGE_NAMES):
                if re.search(rf"\b{re.escape(name)}\s*\(", node.value):
                    violations.append(
                        f"{py_file.relative_to(REPO_ROOT)}:{node.lineno}: calls {name}"
                    )

    assert not violations, (
        f"Retired bridge names still called from e2e tests ({len(violations)}):\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


@pytest.mark.unit
def test_appearance_radios_declare_delegated_actions():
    """Verify that the density and editor-theme radios declare data-action and target identifiers."""
    dashboard_path = REPO_ROOT / "templates" / "dashboard.html"
    content = dashboard_path.read_text(encoding="utf-8")

    input_pattern = re.compile(r"<input\b([^>]*)>", re.IGNORECASE)
    all_inputs = input_pattern.findall(content)

    expected_id_actions = {
        "density-relaxed": "toggle-density",
        "density-compact": "toggle-density",
        "editor-theme-follow": "toggle-editor-theme",
        "editor-theme-light": "toggle-editor-theme",
        "editor-theme-dark": "toggle-editor-theme",
    }

    for input_id, expected_action in expected_id_actions.items():
        matching = [
            attrs for attrs in all_inputs
            if re.search(rf'\bid=["\']{re.escape(input_id)}["\']', attrs)
        ]
        assert matching, (
            f"Expected input with id='{input_id}' in templates/dashboard.html"
        )
        assert len(matching) == 1, (
            f"Expected exactly 1 input with id='{input_id}' in templates/dashboard.html, found {len(matching)}"
        )
        attrs = matching[0]
        action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
        assert action_match, (
            f"Expected input #{input_id} to have a data-action attribute, got: <input{attrs}>"
        )
        assert action_match.group(1) == expected_action, (
            f"Expected input #{input_id} to have data-action='{expected_action}', got: <input{attrs}>"
        )


@pytest.mark.unit
def test_appearance_dispatch_reads_the_input_value():
    """Verify the toggle-density and toggle-editor-theme dispatch entries pass elt.value through.

    Five radios share only two dispatch keys because the handler reads elt.value; a
    hardcoded literal in either entry would silently make every radio in that group
    perform the same action regardless of which one was actually selected.
    """
    js_source = read_static_js()

    for action in ("toggle-density", "toggle-editor-theme"):
        entry_match = re.search(
            r"'" + re.escape(action) + r"'\s*:\s*function\s*\(([^)]*)\)\s*\{"
            r"(?:[^{}]|\{[^{}]*\})*?\}",
            js_source,
        )
        assert entry_match, (
            f"Could not find a '{action}' entry in a delegated dispatch table in JS source"
        )
        entry_body = entry_match.group(0)
        assert re.search(r"\.value\b", entry_body), (
            f"Expected the '{action}' dispatch entry to pass the element's value through "
            "(e.g. elt.value) rather than a hardcoded string literal, since five radios "
            "share only two dispatch keys and a hardcoded literal would silently make "
            f"every radio in that group do the same thing. Entry body: {entry_body}"
        )


@pytest.mark.unit
def test_theme_customization_controls_declare_delegated_actions():
    """Verify that theme customization controls declare data-action and target identifiers."""
    partial_path = REPO_ROOT / "templates" / "partials" / "settings_themes.html"
    content = partial_path.read_text(encoding="utf-8")

    button_pattern = re.compile(r"<button\b([^>]*)>(.*?)</button>", re.IGNORECASE | re.DOTALL)
    all_buttons = button_pattern.findall(content)

    preview_buttons = [
        attrs for attrs, text in all_buttons
        if text.strip() == "Preview"
    ]
    assert preview_buttons, "No 'Preview' buttons found in templates/partials/settings_themes.html"
    assert len(preview_buttons) == 2, (
        f"Expected 2 'Preview' buttons in templates/partials/settings_themes.html, found {len(preview_buttons)}"
    )
    for attrs in preview_buttons:
        action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
        assert action_match, (
            f"Expected 'Preview' button to have a data-action attribute, got: <button{attrs}>"
        )
        assert action_match.group(1) == "apply-theme-preview", (
            f"Expected 'Preview' button to have data-action='apply-theme-preview', got: <button{attrs}>"
        )

    cancel_buttons = [
        attrs for attrs, text in all_buttons
        if text.strip() == "Cancel preview"
    ]
    assert cancel_buttons, "No 'Cancel preview' buttons found in templates/partials/settings_themes.html"
    assert len(cancel_buttons) == 2, (
        f"Expected 2 'Cancel preview' buttons in templates/partials/settings_themes.html, found {len(cancel_buttons)}"
    )
    for attrs in cancel_buttons:
        action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
        assert action_match, (
            f"Expected 'Cancel preview' button to have a data-action attribute, got: <button{attrs}>"
        )
        assert action_match.group(1) == "clear-theme-preview", (
            f"Expected 'Cancel preview' button to have data-action='clear-theme-preview', got: <button{attrs}>"
        )

    mode_buttons = {
        "Light mode": "light",
        "Dark mode": "dark",
    }
    for mode_text, expected_mode in mode_buttons.items():
        matching = [
            attrs for attrs, text in all_buttons
            if text.strip() == mode_text
        ]
        assert matching, (
            f"Expected button with text '{mode_text}' in templates/partials/settings_themes.html"
        )
        assert len(matching) == 1, (
            f"Expected exactly 1 button with text '{mode_text}' in templates/partials/settings_themes.html, found {len(matching)}"
        )
        attrs = matching[0]
        action_match = re.search(r'\bdata-action=["\']([^"\']+)["\']', attrs)
        assert action_match, (
            f"Expected '{mode_text}' button to have a data-action attribute, got: <button{attrs}>"
        )
        assert action_match.group(1) == "set-editor-mode", (
            f"Expected '{mode_text}' button to have data-action='set-editor-mode', got: <button{attrs}>"
        )
        mode_match = re.search(r'\bdata-mode=["\']([^"\']+)["\']', attrs)
        assert mode_match, (
            f"Expected '{mode_text}' button to have a data-mode attribute, got: <button{attrs}>"
        )
        assert mode_match.group(1) == expected_mode, (
            f"Expected '{mode_text}' button to have data-mode='{expected_mode}', got: <button{attrs}>"
        )


@pytest.mark.unit
def test_hx_on_attributes_do_not_reference_retired_names():
    """Verify that htmx hx-on attributes in templates do not reference retired bridge names."""
    templates_dir = REPO_ROOT / "templates"
    hx_on_attr_pattern = re.compile(
        r'\bhx-on[^\s=>]*\s*=\s*(["\'])(.*?)\1', re.IGNORECASE | re.DOTALL
    )

    violations = []
    for html_file in templates_dir.rglob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        for _, handler_code in hx_on_attr_pattern.findall(content):
            for target in sorted(RETIRED_BRIDGE_NAMES):
                if target in handler_code:
                    rel_path = html_file.relative_to(REPO_ROOT)
                    violations.append(f"{rel_path}: hx-on attribute mentions {target}")

    assert not violations, (
        f"Found hx-on attributes referencing retired names in templates ({len(violations)}). "
        "htmx hx-on attribute bodies are evaluated against globals just like inline handlers, "
        "but the inline-handler regex cannot see them:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


@pytest.mark.unit
def test_settings_themes_partial_has_no_inline_script():
    """Verify that templates/partials/settings_themes.html contains no inline script blocks."""
    partial_path = REPO_ROOT / "templates" / "partials" / "settings_themes.html"
    content = partial_path.read_text(encoding="utf-8")

    assert not re.search(r"<script\b", content, re.IGNORECASE), (
        "Expected templates/partials/settings_themes.html to contain no inline <script> blocks. "
        "Template-local script blocks require the same 'unsafe-inline' CSP allowance as inline "
        "event handlers, which this refactoring removes."
    )

