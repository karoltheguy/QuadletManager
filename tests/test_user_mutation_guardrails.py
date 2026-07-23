"""Tests for guardrails on high-stakes user mutations (Issue #222).

Covers:
- templates/partials/settings_users.html's admin toggle checkbox has an
  `hx-confirm` attribute whose value is state-aware (a "Grant admin to"
  branch and a "Revoke admin from" branch, driven by `u[3]`) and includes
  the row's username (`{{ u[1] }}`), so flipping a user's admin status
  requires an explicit, informative confirmation.
- The role `<select>` in the same template deliberately does NOT get an
  `hx-confirm` — only the admin toggle is considered high-stakes enough
  to warrant one.
- api/routes.py's `settings_update_user_role` and `settings_toggle_admin`
  endpoints each set an `HX-Trigger` response header carrying a
  `user-updated` event (with a `message` field) on the success path, so
  the client can surface a confirmation toast.
- static/main.js registers a `document.body.addEventListener('user-updated', ...)`
  handler that surfaces the message into `#status-toast` (styled via the
  `toast-success` class) using `textContent` (or the `el()` helper's text
  argument), never `innerHTML`.
"""
import os
import re

import pytest

SETTINGS_USERS_HTML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "partials", "settings_users.html"
)
ROUTES_PY_PATH = os.path.join(os.path.dirname(__file__), "..", "api", "routes.py")
JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "main.js")


def _settings_users_html():
    with open(SETTINGS_USERS_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _routes_py():
    with open(ROUTES_PY_PATH, encoding="utf-8") as f:
        return f.read()


def _js():
    with open(JS_PATH, encoding="utf-8") as f:
        return f.read()


# =============================================================================
# templates/partials/settings_users.html: admin toggle checkbox hx-confirm
# =============================================================================


class TestSettingsUsersAdminToggleHxConfirm:
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
    def test_admin_toggle_checkbox_has_hx_confirm(self):
        block = self._admin_checkbox_block()
        match = re.search(r'hx-confirm="([^"]*)"', block, re.DOTALL)
        assert match, (
            "expected the admin toggle checkbox to have an hx-confirm "
            f"attribute so flipping admin status prompts for confirmation, found: {block!r}"
        )

    @pytest.mark.unit
    def test_admin_toggle_hx_confirm_is_state_aware_grant_and_revoke(self):
        block = self._admin_checkbox_block()
        match = re.search(r'hx-confirm="([^"]*)"', block, re.DOTALL)
        assert match, "expected to locate the hx-confirm attribute"
        confirm_value = match.group(1)
        assert re.search(r"Grant admin to", confirm_value), (
            "expected the hx-confirm value to include a 'Grant admin to' "
            f"branch for the not-yet-admin case, found: {confirm_value!r}"
        )
        assert re.search(r"Revoke admin from", confirm_value), (
            "expected the hx-confirm value to include a 'Revoke admin "
            f"from' branch for the already-admin case, found: {confirm_value!r}"
        )
        assert "u[3]" in confirm_value, (
            "expected the hx-confirm value to be a Jinja conditional on "
            f"u[3] (current admin state), found: {confirm_value!r}"
        )

    @pytest.mark.unit
    def test_admin_toggle_hx_confirm_references_username(self):
        block = self._admin_checkbox_block()
        match = re.search(r'hx-confirm="([^"]*)"', block, re.DOTALL)
        assert match, "expected to locate the hx-confirm attribute"
        confirm_value = match.group(1)
        assert "{{ u[1] }}" in confirm_value, (
            "expected the hx-confirm value to reference {{ u[1] }} (the "
            f"row's username), found: {confirm_value!r}"
        )


# =============================================================================
# templates/partials/settings_users.html: role select has NO hx-confirm
# =============================================================================


class TestSettingsUsersRoleSelectNoHxConfirm:
    def setup_method(self):
        self.html = _settings_users_html()

    def _role_select_block(self):
        match = re.search(
            r'<select[^>]*hx-put="/api/settings/users/\{\{ u\[0\] \}\}"[^>]*>',
            self.html,
            re.DOTALL,
        )
        assert match, (
            "expected to locate the role <select> in settings_users.html"
        )
        return match.group(0)

    @pytest.mark.unit
    def test_role_select_has_no_hx_confirm(self):
        block = self._role_select_block()
        assert "hx-confirm" not in block, (
            "expected the role <select> to NOT have an hx-confirm "
            "attribute (only the admin toggle is high-stakes enough to "
            f"warrant one), found: {block!r}"
        )


# =============================================================================
# api/routes.py: HX-Trigger user-updated header on success
# =============================================================================


class TestRoutesPyUserUpdatedTrigger:
    def setup_method(self):
        self.src = _routes_py()

    def _function_region(self, def_marker):
        start = self.src.find(def_marker)
        assert start != -1, f"expected to locate {def_marker!r} in routes.py"
        next_decorator = self.src.find("@router.", start)
        assert next_decorator != -1, (
            f"expected another @router. decorator following {def_marker!r} "
            "to bound the search region"
        )
        return self.src[start:next_decorator]

    @pytest.mark.unit
    def test_update_user_role_sets_hx_trigger_user_updated(self):
        region = self._function_region("async def settings_update_user_role")
        assert "HX-Trigger" in region, (
            "expected settings_update_user_role to set an HX-Trigger "
            f"response header on success, region: {region!r}"
        )
        assert "user-updated" in region, (
            "expected settings_update_user_role's HX-Trigger payload to "
            f"include a 'user-updated' event, region: {region!r}"
        )

    @pytest.mark.unit
    def test_toggle_admin_sets_hx_trigger_user_updated(self):
        region = self._function_region("async def settings_toggle_admin")
        assert "HX-Trigger" in region, (
            "expected settings_toggle_admin to set an HX-Trigger response "
            f"header on success, region: {region!r}"
        )
        assert "user-updated" in region, (
            "expected settings_toggle_admin's HX-Trigger payload to "
            f"include a 'user-updated' event, region: {region!r}"
        )


# =============================================================================
# static/main.js: global user-updated listener
# =============================================================================


class TestMainJsUserUpdatedListener:
    def setup_method(self):
        self.js = _js()

    def _find_listener_registration(self):
        return re.search(
            r"""document\.body\.addEventListener\(\s*['"]user-updated['"]""",
            self.js,
        )

    @pytest.mark.unit
    def test_user_updated_listener_registered_on_body(self):
        match = self._find_listener_registration()
        assert match, (
            "expected static/main.js to register a "
            "document.body.addEventListener('user-updated', ...) listener "
            "so successful role/admin changes surface a confirmation toast"
        )

    def _handler_region(self):
        match = self._find_listener_registration()
        assert match, "expected to locate the user-updated listener registration"
        start = match.start()
        end = min(start + 1500, len(self.js))
        return self.js[start:end]

    @pytest.mark.unit
    def test_handler_references_status_toast(self):
        region = self._handler_region()
        assert "status-toast" in region, (
            "expected the user-updated handler to reference the "
            "#status-toast element to display the confirmation message"
        )

    @pytest.mark.unit
    def test_handler_references_toast_success_class(self):
        region = self._handler_region()
        assert "toast-success" in region, (
            "expected the user-updated handler to style the toast with "
            "the toast-success class"
        )

    @pytest.mark.unit
    def test_handler_uses_text_content_not_inner_html(self):
        region = self._handler_region()
        assert "textContent" in region, (
            "expected the user-updated handler to assign the message text "
            "via .textContent (or pass it as a text argument to the el() "
            "helper)"
        )
        assert "innerHTML" not in region, (
            "the user-updated handler must not use innerHTML to insert "
            "the message"
        )
