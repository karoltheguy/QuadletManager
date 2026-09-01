"""Tests for settings form error handling (Issue #220).

Covers:
- templates/dashboard.html has three settings forms (Add Server, Add SSH
  Key, Add User) whose reset must only fire when the request actually
  succeeded; otherwise a failed submit silently wipes the user's input
  with no feedback. Issue #392 moved the reset off an
  `hx-on::after-request` attribute onto a `data-after-request="reset-form"`
  declaration, so the gate now lives in the delegated dispatcher and both
  halves are asserted here.
- templates/partials/settings_themes.html has the same bug on its New
  Theme form.
- static/main.js must register a global `htmx:responseError` listener on
  `document.body` that surfaces the FastAPI error detail (from the JSON
  body `{"detail": "..."}` in the failed response) into the
  `#status-toast` element via `textContent` (not `innerHTML`, to avoid
  injecting untrusted content as HTML).
"""
import os
import re

import pytest

from tests.js_source import read_static_js

DASHBOARD_HTML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "dashboard.html"
)
SETTINGS_THEMES_HTML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "partials", "settings_themes.html"
)
TOAST_JS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "static", "modules", "toast.js"
)

# Matches a bare, unconditional `this.reset()` inside an
# hx-on::after-request attribute value (i.e. the whole attribute value is
# just `this.reset()`, with no gating condition present).
UNCONDITIONAL_RESET_ATTR_RE = re.compile(
    r'hx-on::after-request="\s*this\.reset\(\)\s*"'
)

# Matches a form declaring the delegated reset action that replaced the
# hx-on::after-request attribute in issue #392.
RESET_FORM_ATTR_RE = re.compile(r'data-after-request="reset-form"')


def _reset_form_handler_body():
    """The body of the delegated 'reset-form' handler in the static JS."""
    js = read_static_js()
    start = js.find("'reset-form'")
    assert start != -1, (
        "expected a quoted 'reset-form' action in the delegated "
        "htmx:afterRequest dispatcher"
    )
    end = js.find("},", start)
    assert end != -1, "could not find the end of the 'reset-form' handler body"
    return js[start:end]


def _js():
    return read_static_js()


def _dashboard_html():
    with open(DASHBOARD_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _settings_themes_html():
    with open(SETTINGS_THEMES_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _toast_js():
    with open(TOAST_JS_PATH, encoding="utf-8") as f:
        return f.read()


# =============================================================================
# templates/dashboard.html: Add Server / Add SSH Key / Add User forms
# =============================================================================


class TestDashboardSettingsFormResetGating:
    def setup_method(self):
        self.html = _dashboard_html()

    @pytest.mark.unit
    def test_no_unconditional_reset_in_dashboard_forms(self):
        matches = UNCONDITIONAL_RESET_ATTR_RE.findall(self.html)
        assert not matches, (
            "found unconditional this.reset() in hx-on::after-request "
            f"attribute(s) in dashboard.html: {matches!r}; a reset on a "
            "failed submit wipes user input without showing an error"
        )

    @pytest.mark.unit
    def test_settings_forms_declare_the_delegated_reset_action(self):
        matches = RESET_FORM_ATTR_RE.findall(self.html)
        assert len(matches) >= 3, (
            "expected at least 3 forms in dashboard.html (Add Server, "
            "Add SSH Key, Add User) to declare "
            f'data-after-request="reset-form"; found {len(matches)}'
        )

    @pytest.mark.unit
    def test_delegated_reset_gates_on_successful_request(self):
        body = _reset_form_handler_body()
        assert "successful" in body, (
            "expected the delegated 'reset-form' handler to gate its reset() "
            f"call on the request being successful; body was: {body!r}"
        )
        assert ".reset()" in body, (
            "expected the delegated 'reset-form' handler to call reset() on "
            f"the form; body was: {body!r}"
        )


# =============================================================================
# templates/partials/settings_themes.html: New Theme form
# =============================================================================


class TestSettingsThemesFormResetGating:
    def setup_method(self):
        self.html = _settings_themes_html()

    @pytest.mark.unit
    def test_no_unconditional_reset_in_new_theme_form(self):
        matches = UNCONDITIONAL_RESET_ATTR_RE.findall(self.html)
        assert not matches, (
            "found unconditional this.reset() in hx-on::after-request "
            f"attribute(s) in settings_themes.html: {matches!r}; a reset "
            "on a failed submit wipes user input without showing an error"
        )

    @pytest.mark.unit
    def test_new_theme_form_declares_the_delegated_reset_action(self):
        matches = RESET_FORM_ATTR_RE.findall(self.html)
        assert matches, (
            "expected the New Theme form in settings_themes.html to declare "
            'data-after-request="reset-form", so the delegated dispatcher '
            "gates its reset on the request succeeding"
        )


# =============================================================================
# static/main.js: global htmx:responseError listener
# =============================================================================


class TestMainJsResponseErrorListener:
    def setup_method(self):
        self.js = _js()

    def _find_listener_registration(self):
        match = re.search(
            r"""document\.body\.addEventListener\(\s*['"]htmx:responseError['"]""",
            self.js,
        )
        return match

    @pytest.mark.unit
    def test_response_error_listener_registered_on_body(self):
        match = self._find_listener_registration()
        assert match, (
            "expected static/main.js to register a "
            "document.body.addEventListener('htmx:responseError', ...) "
            "listener so failed submits surface an error message instead "
            "of silently failing"
        )

    def _handler_region(self):
        match = self._find_listener_registration()
        assert match, "expected to locate the htmx:responseError listener registration"
        start = match.start()
        # A generous window covering the handler body; not the whole file,
        # so innerHTML usage elsewhere in main.js doesn't leak in.
        end = min(start + 1500, len(self.js))
        return self.js[start:end]

    @pytest.mark.unit
    def test_handler_references_status_toast(self):
        region = self._handler_region()
        assert "showToast" in region, (
            "expected the htmx:responseError handler to render through "
            "the shared showToast helper"
        )

    @pytest.mark.unit
    def test_handler_parses_json_detail_from_response_text(self):
        region = self._handler_region()
        assert "responseText" in region, (
            "expected the htmx:responseError handler to read "
            "xhr.responseText from the failed request"
        )
        assert re.search(r"""['"]detail['"]|\.detail\b""", region), (
            "expected the htmx:responseError handler to parse the JSON "
            "'detail' field from the FastAPI error response "
            '(e.g. {"detail": "..."})'
        )

    @pytest.mark.unit
    def test_handler_uses_text_content_not_inner_html(self):
        region = self._handler_region()
        assert "showToast" in region, (
            "expected the htmx:responseError handler to render through "
            "the shared showToast helper"
        )
        toast_js = _toast_js()
        assert "textContent" in toast_js, (
            "expected static/modules/toast.js to assign the error "
            "message via .textContent"
        )
        assert "innerHTML" not in toast_js, (
            "static/modules/toast.js must not use innerHTML to "
            "insert the (potentially untrusted) error message"
        )
