"""Tests for admin panel UI visibility (issue #34).

Verifies that the dashboard_view route passes is_admin to the template and
that admin-gated sections are present/absent based on the flag.
"""
import sys
import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# =============================================================================
# dashboard_view passes is_admin to template
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_current_user_is_admin', return_value=True)
@patch('api.routes.get_current_user_role', return_value='editor')
async def test_dashboard_view_passes_is_admin_true(mock_role, mock_admin):
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
        )

    assert 'is_admin' in captured
    assert captured['is_admin'] is True


@pytest.mark.asyncio
async def test_dashboard_view_passes_is_admin_false():
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
        )

    assert 'is_admin' in captured
    assert captured['is_admin'] is False


# =============================================================================
# settings_servers partial respects is_admin
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_settings_list_servers_includes_is_admin_in_context(mock_db):
    """settings_list_servers must pass is_admin to the template context."""
    from api.routes import settings_list_servers

    _select = MagicMock()

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

    template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template('dashboard.html')
    return template.render(user_role=user_role, is_admin=is_admin)


def test_admin_sees_server_management_form():
    """Admin users must see the Add Server form in the Settings pane."""
    html = _render_dashboard(is_admin=True, user_role='editor')
    assert 'hx-post="/api/settings/servers"' in html


def test_non_admin_does_not_see_server_management_form():
    """Non-admin users must NOT see the Add Server form."""
    html = _render_dashboard(is_admin=False, user_role='editor')
    assert 'hx-post="/api/settings/servers"' not in html


def test_admin_sees_user_management_form():
    """Admin users must see the Add User form."""
    html = _render_dashboard(is_admin=True, user_role='editor')
    assert 'hx-post="/api/settings/users"' in html


def test_non_admin_does_not_see_user_management_form():
    """Non-admin users must NOT see the Add User form."""
    html = _render_dashboard(is_admin=False, user_role='editor')
    assert 'hx-post="/api/settings/users"' not in html


def test_admin_sees_ssh_key_section():
    """Admin users must see the SSH Key Management section."""
    html = _render_dashboard(is_admin=True, user_role='editor')
    assert '/api/keys' in html


def test_non_admin_does_not_see_ssh_key_section():
    """Non-admin users must NOT see the SSH Key Management section."""
    html = _render_dashboard(is_admin=False, user_role='editor')
    assert 'hx-post="/api/keys"' not in html


def test_viewer_non_admin_does_not_see_admin_sections():
    """Viewer role without admin flag must see no admin sections."""
    html = _render_dashboard(is_admin=False, user_role='viewer')
    assert 'hx-post="/api/settings/servers"' not in html
    assert 'hx-post="/api/settings/users"' not in html
    assert 'hx-post="/api/keys"' not in html


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


def test_admin_sees_remove_button_in_servers_list():
    """Admin must see the Remove button for each server."""
    html = _render_settings_servers(is_admin=True)
    assert 'Remove' in html


def test_non_admin_does_not_see_remove_button_in_servers_list():
    """Non-admin must NOT see the Remove button."""
    html = _render_settings_servers(is_admin=False)
    assert 'Remove' not in html
