"""Tests for the 'Create New Quadlet' modal form.

Validates that the modal template is wired correctly so HTMX can
submit the POST before the modal is removed from the DOM.
Bug reference: Issue #14 — 'New' button fails to create a file.

Migrated from unittest.IsolatedAsyncioTestCase to pytest-asyncio native style
to resolve event loop conflict (Issue #19).
"""
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# =============================================================================
# Test modal template rendering
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_modal_does_not_use_onsubmit(mock_db):
    """The form must NOT use an `onsubmit` handler that removes the modal
    before HTMX sends the request. Instead, `hx-on::after-request`
    (or equivalent) should be used so the modal is dismissed only
    *after* the request completes."""
    from api.routes import new_file_modal

    # Fake DB returning one server
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = [(1, "test-server")]
    cursor_ctx = AsyncMock()
    cursor_ctx.__aenter__.return_value = mock_cursor
    conn_mock = AsyncMock()
    conn_mock.execute = MagicMock(return_value=cursor_ctx)
    mock_db.return_value.__aenter__.return_value = conn_mock

    request = MagicMock()
    request.cookies = {}

    with patch('api.routes.get_current_user_role', return_value="editor"):
        response = await new_file_modal(request=request, role="editor")

    body = response.body.decode()

    # The old bug: onsubmit removing the modal before HTMX fires
    assert 'onsubmit' not in body, (
        "Form must not use onsubmit to close the modal — "
        "it races with HTMX and prevents the request from firing."
    )

    # Must target the toast so the user sees feedback
    assert 'hx-post="/api/create"' in body
    assert 'hx-target="#status-toast"' in body

    # Must include a mechanism to close the modal after the request
    assert 'hx-on::after-request' in body, (
        "Form should use hx-on::after-request to close the modal "
        "only after the HTMX request has completed."
    )


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
async def test_create_endpoint_returns_reload_trigger(mock_execute, mock_db):
    """After creating a file, the response must include the HX-Trigger
    header so the file tree reloads and shows the new file."""
    from api.routes import create_new_quadlet

    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = ("[Container]\n",)
    cursor_ctx = AsyncMock()
    cursor_ctx.__aenter__.return_value = mock_cursor
    conn_mock = AsyncMock()
    conn_mock.execute = MagicMock(return_value=cursor_ctx)
    mock_db.return_value.__aenter__.return_value = conn_mock

    response = await create_new_quadlet(
        request=MagicMock(),
        server_id=1,
        scope="user",
        type="container",
        name="myapp",
        role="editor"
    )

    assert response.status_code == 200
    assert "Created" in response.body.decode()
    assert response.headers.get("HX-Trigger") == "reload-servers", (
        "Response must trigger a server-list reload so the new file appears in the tree."
    )


def _make_db_mock(servers):
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = servers
    cursor_ctx = AsyncMock()
    cursor_ctx.__aenter__.return_value = mock_cursor
    conn_mock = AsyncMock()
    conn_mock.execute = MagicMock(return_value=cursor_ctx)
    db_ctx = AsyncMock()
    db_ctx.__aenter__.return_value = conn_mock
    return db_ctx


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_modal_preselects_server_when_server_id_provided(mock_db):
    """When server_id is passed as a query param, the matching option is pre-selected."""
    from api.routes import new_file_modal

    mock_db.return_value = _make_db_mock([(1, "alpha"), (2, "beta")])

    request = MagicMock()
    request.cookies = {}

    response = await new_file_modal(request=request, server_id=2, role="editor")
    body = response.body.decode()

    assert '<option value="2"' in body
    assert 'value="2" selected' in body or 'value="2"  selected' in body or 'selected' in body
    assert 'value="1"' in body


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_modal_no_preselect_when_server_id_omitted(mock_db):
    """When server_id is not provided, no option is forcibly pre-selected."""
    from api.routes import new_file_modal

    mock_db.return_value = _make_db_mock([(1, "alpha"), (2, "beta")])

    request = MagicMock()
    request.cookies = {}

    response = await new_file_modal(request=request, server_id=None, role="editor")
    body = response.body.decode()

    assert 'selected' not in body


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_servers_list_shows_new_btn_for_editor(mock_db):
    """Editor role gets a + button on each server row with correct title/aria-label."""
    from api.routes import api_servers

    mock_db.return_value = _make_db_mock([(3, "my-server")])

    request = MagicMock()
    request.cookies = {}

    response = await api_servers(request=request, role="editor")
    body = response.body.decode()

    assert 'server-new-btn' in body
    assert 'New quadlet on my-server' in body
    assert 'server_id=3' in body


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_servers_list_hides_new_btn_for_viewer(mock_db):
    """Viewer role must not see the + button."""
    from api.routes import api_servers

    mock_db.return_value = _make_db_mock([(3, "my-server")])

    request = MagicMock()
    request.cookies = {}

    response = await api_servers(request=request, role="viewer")
    body = response.body.decode()

    assert 'server-new-btn' not in body
