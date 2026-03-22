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
