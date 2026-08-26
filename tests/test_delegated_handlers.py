"""Tests for delegated navigation event handlers (issue #401).

These tests specify replacing inline onclick handlers for top navigation and settings
sidenav buttons with data-action attributes and a delegated document click listener,
allowing switchTab and showSettingsSection to be removed from the window bridge.
"""
import pathlib
import re

import pytest

from tests.js_source import read_static_js

REPO_ROOT = pathlib.Path(__file__).parent.parent


@pytest.mark.unit
def test_nav_handlers_are_not_inline():
    """Verify that templates do not use inline switchTab or showSettingsSection event handlers."""
    templates_dir = REPO_ROOT / "templates"
    inline_handler_attr_pattern = re.compile(
        r'\bon[a-z]+\s*=\s*(["\'])(.*?)\1', re.IGNORECASE | re.DOTALL
    )

    violations = []
    for html_file in templates_dir.rglob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        for _, handler_code in inline_handler_attr_pattern.findall(content):
            for target in ("switchTab", "showSettingsSection"):
                if target in handler_code:
                    rel_path = html_file.relative_to(REPO_ROOT)
                    violations.append(f"{rel_path}: inline handler mentions {target}")

    assert not violations, (
        f"Found inline nav handlers in templates ({len(violations)}):\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


@pytest.mark.unit
def test_nav_names_are_off_the_window_bridge():
    """Verify that switchTab and showSettingsSection are removed from the window bridge."""
    js_source = read_static_js()
    bridge_match = re.search(
        r"Object\.assign\s*\(\s*window\s*,\s*\{(.*?)\}\s*\)",
        js_source,
        re.DOTALL,
    )
    assert bridge_match, "Could not find Object.assign(window, { ... }) bridge block in JS source"
    bridge_body = bridge_match.group(1)
    bridge_keys = set(re.findall(r"\b([A-Za-z_$][\w$]*)\b", bridge_body))

    forbidden_keys = {"switchTab", "showSettingsSection"}
    exposed_forbidden = sorted(bridge_keys & forbidden_keys)
    assert not exposed_forbidden, (
        f"Expected switchTab and showSettingsSection to be removed from window bridge, but found: {exposed_forbidden}"
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
def test_js_dispatches_the_delegated_nav_actions():
    """Verify that static JS contains delegated nav action handlers and a click listener."""
    js_source = read_static_js()

    assert "switch-tab" in js_source, (
        "Expected 'switch-tab' action name string in static JS source"
    )
    assert "show-settings-section" in js_source, (
        "Expected 'show-settings-section' action name string in static JS source"
    )
    assert "document.addEventListener('click'" in js_source, (
        "Expected static JS to register a document-level click listener with document.addEventListener('click'"
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
