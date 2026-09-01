"""Tests for admin panel UI visibility (issue #34).

Verifies that the dashboard_view route passes is_admin to the template and
that admin-gated sections are present/absent based on the flag.
"""
import sys
import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from tests.js_source import read_static_js

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# =============================================================================
# dashboard_view passes is_admin to template
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes._ensure_default_theme', new_callable=AsyncMock)
@patch('api.routes.load_active_theme', new_callable=AsyncMock,
       return_value={"mode_pref": "auto", "light": {}, "dark": {}})
@patch('api.routes.get_current_user_is_admin', return_value=True)
@patch('api.routes.get_current_user_role', return_value='editor')
@pytest.mark.unit
async def test_dashboard_view_passes_is_admin_true(mock_role, mock_admin, mock_load, mock_ensure):
    """dashboard_view must include is_admin=True for admin sessions."""
    from api.routes import dashboard_view

    captured = {}

    def fake_response(request, template, context):
        captured.update(context)
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<html></html>")

    request = MagicMock()
    with patch('api.routes.templates.TemplateResponse', side_effect=fake_response):
        await dashboard_view(
            request=request,
            role='editor',
            is_admin=True,
            username='admin',
            user_id=1,
        )

    assert 'is_admin' in captured
    assert captured['is_admin'] is True


@pytest.mark.asyncio
@patch('api.routes._ensure_default_theme', new_callable=AsyncMock)
@patch('api.routes.load_active_theme', new_callable=AsyncMock,
       return_value={"mode_pref": "auto", "light": {}, "dark": {}})
@pytest.mark.unit
async def test_dashboard_view_passes_is_admin_false(mock_load, mock_ensure):
    """dashboard_view must include is_admin=False for non-admin sessions."""
    from api.routes import dashboard_view

    captured = {}

    def fake_response(request, template, context):
        captured.update(context)
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<html></html>")

    request = MagicMock()
    with patch('api.routes.templates.TemplateResponse', side_effect=fake_response):
        await dashboard_view(
            request=request,
            role='viewer',
            is_admin=False,
            username='user',
            user_id=2,
        )

    assert 'is_admin' in captured
    assert captured['is_admin'] is False


# =============================================================================
# settings_servers partial respects is_admin
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@pytest.mark.unit
async def test_settings_list_servers_includes_is_admin_in_context(mock_db):
    """settings_list_servers must pass is_admin to the template context."""
    from api.routes import settings_list_servers

    class _FetchAllMock:
        def __await__(self):
            async def _noop(): pass
            return _noop().__await__()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def fetchall(self):
            return [(1, "server1", "192.168.1.1", "ubuntu", "my-key")]

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(return_value=_FetchAllMock())
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    captured = {}

    def fake_response(request, template, context):
        captured.update(context)
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<html></html>")

    with patch('api.routes.templates.TemplateResponse', side_effect=fake_response):
        await settings_list_servers(
            request=MagicMock(),
            role='editor',
            is_admin=True,
        )

    assert 'is_admin' in captured
    assert captured['is_admin'] is True


# =============================================================================
# Admin panel HTML sections are present for admins and absent for non-admins
# =============================================================================


def _render_dashboard(is_admin: bool, user_role: str = 'editor') -> str:
    """Render dashboard.html with Jinja2 directly and return the HTML string."""
    from jinja2 import Environment, FileSystemLoader
    import os
    from types import SimpleNamespace

    from api.routes import asset_url, module_import_map

    template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
    env = Environment(loader=FileSystemLoader(template_dir))
    # This bare Environment is not the app's, so it needs the app's Jinja
    # globals wired in explicitly or dashboard.html cannot render.
    env.globals['asset_url'] = asset_url
    env.globals['module_import_map'] = module_import_map
    template = env.get_template('dashboard.html')
    # dashboard.html reads request.state.csp_nonce for the import map's CSP
    # nonce (#472). The app supplies it from middleware; this bare render has
    # no real request, so stand one in.
    request = SimpleNamespace(state=SimpleNamespace(csp_nonce="test-nonce"))
    return template.render(
        request=request,
        user_role=user_role,
        is_admin=is_admin,
        active_theme_mode_pref="auto",
        active_theme_light={},
        active_theme_dark={},
    )


@pytest.mark.unit
def test_admin_sees_server_management_form():
    """Admin users must see the Add Server form in the Settings pane."""
    html = _render_dashboard(is_admin=True, user_role='editor')
    assert 'hx-post="/api/settings/servers"' in html


@pytest.mark.unit
def test_non_admin_does_not_see_server_management_form():
    """Non-admin users must NOT see the Add Server form."""
    html = _render_dashboard(is_admin=False, user_role='editor')
    assert 'hx-post="/api/settings/servers"' not in html


@pytest.mark.unit
def test_admin_sees_user_management_form():
    """Admin users must see the Add User form."""
    html = _render_dashboard(is_admin=True, user_role='editor')
    assert 'hx-post="/api/settings/users"' in html


@pytest.mark.unit
def test_non_admin_does_not_see_user_management_form():
    """Non-admin users must NOT see the Add User form."""
    html = _render_dashboard(is_admin=False, user_role='editor')
    assert 'hx-post="/api/settings/users"' not in html


@pytest.mark.unit
def test_admin_sees_ssh_key_section():
    """Admin users must see the SSH Key Management section."""
    html = _render_dashboard(is_admin=True, user_role='editor')
    assert '/api/keys' in html


@pytest.mark.unit
def test_non_admin_does_not_see_ssh_key_section():
    """Non-admin users must NOT see the SSH Key Management section."""
    html = _render_dashboard(is_admin=False, user_role='editor')
    assert 'hx-post="/api/keys"' not in html


@pytest.mark.unit
def test_viewer_non_admin_does_not_see_admin_sections():
    """Viewer role without admin flag must see no admin sections."""
    html = _render_dashboard(is_admin=False, user_role='viewer')
    assert 'hx-post="/api/settings/servers"' not in html
    assert 'hx-post="/api/settings/users"' not in html
    assert 'hx-post="/api/keys"' not in html


@pytest.mark.unit
def test_admin_sees_admin_tab_and_session_duration_section():
    """Admin users must see the Admin sidenav tab and session duration control (issue #124)."""
    html = _render_dashboard(is_admin=True, user_role='editor')
    assert 'data-section="admin"' in html
    assert 'hx-get="/api/settings/session-duration"' in html


@pytest.mark.unit
def test_non_admin_does_not_see_admin_tab_or_session_duration_section():
    """Non-admin users must NOT see the Admin sidenav tab or session duration control."""
    html = _render_dashboard(is_admin=False, user_role='editor')
    assert 'data-section="admin"' not in html
    assert 'hx-get="/api/settings/session-duration"' not in html


# =============================================================================
# settings_servers partial: Remove button visibility
# =============================================================================


def _render_settings_servers(is_admin: bool) -> str:
    from jinja2 import Environment, FileSystemLoader
    import os

    template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template('partials/settings_servers.html')
    servers = [(1, 'my-server', '10.0.0.1', 'ubuntu', 'deploy-key')]
    return template.render(servers=servers, is_admin=is_admin)


@pytest.mark.unit
def test_admin_sees_remove_button_in_servers_list():
    """Admin must see the Remove button for each server."""
    html = _render_settings_servers(is_admin=True)
    assert 'Remove' in html


@pytest.mark.unit
def test_non_admin_does_not_see_remove_button_in_servers_list():
    """Non-admin must NOT see the Remove button."""
    html = _render_settings_servers(is_admin=False)
    assert 'Remove' not in html


@pytest.mark.unit
def test_reset_host_key_button_renamed_and_in_edit_panel():
    """The 'Re-pin host key' button must be renamed to 'Reset host key' and
    relocated into the per-server edit panel (issue #229)."""
    html = _render_settings_servers(is_admin=True)
    # 1. renamed: old misleading label gone, accurate label present
    assert 'Re-pin host key' not in html
    assert 'Reset host key' in html
    # 2. relocated: the repin action now lives inside the per-server edit panel
    #    (after the server-edit-row marker), not in the top-level actions cell
    assert 'server-edit-row-1' in html
    assert html.index('repin-host-key') > html.index('server-edit-row-1')


# =============================================================================
# servers-list HTMX error handling and refresh trigger (issue #103)
# =============================================================================


@pytest.mark.unit
def test_servers_list_div_has_refresh_servers_trigger():
    """#servers-list must listen for refresh-servers to support reorder-driven reloads."""
    html = _render_dashboard(is_admin=True)
    assert 'refresh-servers' in html


@pytest.mark.unit
def test_servers_list_response_error_is_handled_in_js():
    """A #servers-list load failure must still surface, now via a delegated listener.

    The handler moved out of an hx-on::response-error attribute in issue #392,
    so the guarantee from #103 is asserted against the JS that replaced it.
    """
    js = read_static_js()
    assert 'htmx:responseError' in js
    assert 'retry-servers-list' in js


@pytest.mark.unit
def test_servers_list_send_error_is_handled_in_js():
    """A #servers-list network failure must still surface, now via a delegated listener."""
    js = read_static_js()
    assert 'htmx:sendError' in js
    assert 'retry-servers-list' in js


@pytest.mark.unit
def test_reorder_handler_dispatches_refresh_servers_event():
    """The drag-and-drop reorder handler must dispatch refresh-servers, not call htmx.process(target)."""
    assert 'refresh-servers' in read_static_js()


@pytest.mark.unit
def test_reorder_handler_does_not_call_htmx_process_on_outer_target():
    """The reorder handler must not call htmx.process(target) on #servers-list (re-fires load trigger)."""
    assert 'htmx.process(target)' not in read_static_js()
