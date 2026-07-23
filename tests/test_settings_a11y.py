"""Tests for settings focus + labeling accessibility (Issue #221).

Covers:
- static/style.css defines a global `:focus-visible` rule (not scoped to a
  single class) with a visible `outline` using `var(--brand-primary)` at
  `2px` width, plus an `outline-offset` declaration, so keyboard focus is
  clearly visible throughout the app.
- static/main.js's `window.showSettingsSection` function also manages the
  `aria-current` attribute on `.settings-sidenav-item` buttons (in addition
  to toggling the `active` class), so assistive tech can announce which
  settings section is currently selected.
- templates/dashboard.html's initially-active settings sidenav button
  (Servers) carries `aria-current="true"` to match its initial `active`
  class state.
- templates/partials/settings_users.html's per-row admin toggle checkbox
  has an `aria-label` that names both "admin" and the row's username
  (`{{ u[1] }}`), so each checkbox has a distinct accessible name.
- templates/partials/settings_themes.html's light/dark color-editor loops
  give every `.color-key-label` a `for` attribute pointing at its paired
  text input (`light-{{ loop.index }}` / `dark-{{ loop.index }}`), instead
  of leaving the label unassociated with its input.
"""
import os
import re

import pytest

STYLE_CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")
JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "main.js")
DASHBOARD_HTML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "dashboard.html"
)
SETTINGS_USERS_HTML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "partials", "settings_users.html"
)
SETTINGS_THEMES_HTML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "partials", "settings_themes.html"
)


def _style_css():
    with open(STYLE_CSS_PATH, encoding="utf-8") as f:
        return f.read()


def _js():
    with open(JS_PATH, encoding="utf-8") as f:
        return f.read()


def _dashboard_html():
    with open(DASHBOARD_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _settings_users_html():
    with open(SETTINGS_USERS_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _settings_themes_html():
    with open(SETTINGS_THEMES_HTML_PATH, encoding="utf-8") as f:
        return f.read()


# =============================================================================
# static/style.css: global :focus-visible outline rule
# =============================================================================


class TestStyleCssFocusVisible:
    def setup_method(self):
        self.css = _style_css()

    def _find_focus_visible_rule(self):
        # Locate a CSS rule (selector list { declarations }) whose selector
        # list contains a bare `:focus-visible` (i.e. not scoped as part of
        # a compound selector like `.foo:focus-visible`).
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", self.css):
            selector_list = match.group(1)
            selectors = [s.strip() for s in selector_list.split(",")]
            if ":focus-visible" in selectors:
                return match.group(2)
        return None

    @pytest.mark.unit
    def test_global_focus_visible_selector_present(self):
        body = self._find_focus_visible_rule()
        assert body is not None, (
            "expected a CSS rule in style.css with a bare, global "
            "`:focus-visible` selector (not scoped to a class like "
            "`.foo:focus-visible`)"
        )

    @pytest.mark.unit
    def test_focus_visible_rule_sets_brand_primary_outline_2px(self):
        body = self._find_focus_visible_rule()
        assert body is not None, "expected to locate the :focus-visible rule"
        assert re.search(
            r"outline\s*:[^;]*var\(\s*--brand-primary\s*\)[^;]*2px",
            body,
        ) or re.search(
            r"outline\s*:[^;]*2px[^;]*var\(\s*--brand-primary\s*\)",
            body,
        ), (
            "expected the :focus-visible rule to set an `outline` using "
            "var(--brand-primary) at a width of 2px, found declarations: "
            f"{body!r}"
        )

    @pytest.mark.unit
    def test_focus_visible_rule_sets_outline_offset(self):
        body = self._find_focus_visible_rule()
        assert body is not None, "expected to locate the :focus-visible rule"
        assert re.search(r"outline-offset\s*:", body), (
            "expected the :focus-visible rule to include an "
            f"outline-offset declaration, found declarations: {body!r}"
        )


# =============================================================================
# static/main.js: window.showSettingsSection manages aria-current
# =============================================================================


class TestMainJsShowSettingsSectionAriaCurrent:
    def setup_method(self):
        self.js = _js()

    def _function_region(self):
        start = self.js.find("window.showSettingsSection")
        assert start != -1, (
            "expected to locate window.showSettingsSection in main.js"
        )
        # Extract from this assignment up to the next top-level `window.`
        # assignment, so the check is scoped to this function only.
        next_window_idx = self.js.find("window.", start + len("window."))
        assert next_window_idx != -1, (
            "expected another window.* assignment following "
            "showSettingsSection to bound the search region"
        )
        return self.js[start:next_window_idx]

    @pytest.mark.unit
    def test_show_settings_section_toggles_active_class_sanity_check(self):
        region = self._function_region()
        assert "settings-sidenav-item" in region
        assert "classList.toggle" in region

    @pytest.mark.unit
    def test_show_settings_section_manages_aria_current(self):
        region = self._function_region()
        assert "aria-current" in region, (
            "expected window.showSettingsSection to also manage the "
            "aria-current attribute (via setAttribute/removeAttribute or "
            "equivalent) on .settings-sidenav-item buttons, not just toggle "
            "the 'active' class"
        )


# =============================================================================
# templates/dashboard.html: initial settings sidenav button aria-current
# =============================================================================


class TestDashboardSettingsSidenavAriaCurrent:
    def setup_method(self):
        self.html = _dashboard_html()

    @pytest.mark.unit
    def test_active_servers_sidenav_button_has_aria_current_true(self):
        match = re.search(
            r'<button[^>]*class="settings-sidenav-item active"[^>]*data-section="servers"[^>]*>',
            self.html,
        )
        assert match, (
            "expected to locate the initially-active Servers settings "
            "sidenav button in dashboard.html"
        )
        assert 'aria-current="true"' in match.group(0), (
            "expected the initially-active settings sidenav button to "
            'carry aria-current="true", found: ' + match.group(0)
        )


# =============================================================================
# templates/partials/settings_users.html: admin toggle checkbox aria-label
# =============================================================================


class TestSettingsUsersAdminToggleAriaLabel:
    def setup_method(self):
        self.html = _settings_users_html()

    def _admin_checkbox_block(self):
        match = re.search(
            r'<input type="checkbox"[^>]*title="Toggle admin privileges"[^>]*>',
            self.html,
            re.DOTALL,
        )
        assert match, (
            "expected to locate the admin toggle checkbox in "
            "settings_users.html"
        )
        return match.group(0)

    @pytest.mark.unit
    def test_admin_toggle_checkbox_has_aria_label_with_username(self):
        block = self._admin_checkbox_block()
        match = re.search(r'aria-label="([^"]*)"', block)
        assert match, (
            "expected the admin toggle checkbox to have an aria-label "
            f"attribute with a per-row accessible name, found: {block!r}"
        )
        aria_label = match.group(1)
        assert re.search(r"admin", aria_label, re.IGNORECASE), (
            "expected the aria-label to mention 'Admin', found: "
            f"{aria_label!r}"
        )
        assert "{{ u[1] }}" in aria_label, (
            "expected the aria-label to include the Jinja expression "
            "{{ u[1] }} (the row's username) so each checkbox has a "
            f"distinct accessible name, found: {aria_label!r}"
        )


# =============================================================================
# templates/partials/settings_themes.html: color-key-label `for` attributes
# =============================================================================


class TestSettingsThemesColorLabelFor:
    def setup_method(self):
        self.html = _settings_themes_html()

    @pytest.mark.unit
    def test_light_color_label_has_for_attribute(self):
        assert re.search(
            r'<label[^>]*for="light-\{\{\s*loop\.index\s*\}\}"[^>]*class="color-key-label"'
            r'|<label[^>]*class="color-key-label"[^>]*for="light-\{\{\s*loop\.index\s*\}\}"',
            self.html,
        ), (
            "expected a label with for=\"light-{{ loop.index }}\" in "
            "settings_themes.html"
        )

    @pytest.mark.unit
    def test_dark_color_label_has_for_attribute(self):
        assert re.search(
            r'<label[^>]*for="dark-\{\{\s*loop\.index\s*\}\}"[^>]*class="color-key-label"'
            r'|<label[^>]*class="color-key-label"[^>]*for="dark-\{\{\s*loop\.index\s*\}\}"',
            self.html,
        ), (
            "expected a label with for=\"dark-{{ loop.index }}\" in "
            "settings_themes.html"
        )

    @pytest.mark.unit
    def test_no_color_key_label_left_without_for_attribute(self):
        unlabeled = re.findall(
            r'<label class="color-key-label">', self.html
        )
        assert not unlabeled, (
            "found .color-key-label element(s) with no `for` attribute in "
            f"settings_themes.html: {len(unlabeled)} occurrence(s)"
        )
