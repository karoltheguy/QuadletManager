"""Tests for RBAC (Role-Based Access Control) in API routes.

Migrated from unittest.IsolatedAsyncioTestCase to pytest-asyncio native style
to resolve event loop conflict (Issue #19).
"""
import sys
import os
import pytest
from fastapi import HTTPException
from unittest.mock import patch, AsyncMock, MagicMock

# Add parent directory to path to import routes
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# =============================================================================
# Test viewer role restrictions
# =============================================================================


@pytest.mark.asyncio
async def test_viewer_cannot_save():
    from api.routes import save_file

    role = "viewer"

    with pytest.raises(HTTPException) as exc_info:
        await save_file(
            request=MagicMock(),
            server_id=1,
            file_path="/fake/path",
            scope="user",
            unit_name="fake.service",
            content="data",
            role=role
        )

    assert exc_info.value.status_code == 403
    msg = exc_info.value.detail
    assert "cannot create files" in msg or "cannot save" in msg


@pytest.mark.asyncio
async def test_viewer_cannot_create():
    from api.routes import create_new_quadlet

    role = "viewer"

    with pytest.raises(HTTPException) as exc_info:
        await create_new_quadlet(
            request=MagicMock(),
            server_id=1,
            scope="user",
            type="container",
            name="test",
            role=role
        )

    assert exc_info.value.status_code == 403
    assert "cannot create files" in exc_info.value.detail


@pytest.mark.asyncio
async def test_viewer_cannot_systemctl_post():
    from api.routes import api_systemctl_post

    role = "viewer"

    # viewer can check status (action="status")
    with patch('api.routes.systemctl_action', new_callable=AsyncMock) as mock_action:
        mock_action.return_value = "fake status"
        response = await api_systemctl_post(
            server_id=1,
            action="status",
            unit="fake.service",
            scope="user",
            role=role
        )
        assert response.status_code == 200

    # viewer cannot start
    response_forbid = await api_systemctl_post(
        server_id=1,
        action="start",
        unit="fake.service",
        scope="user",
        role=role
    )
    assert response_forbid.status_code == 403
    assert response_forbid.body.decode() == "Permission denied"


# =============================================================================
# Test editor role permissions
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@patch('api.routes.reload_and_restart', new_callable=AsyncMock)
@patch('api.routes.systemctl_action', new_callable=AsyncMock)
async def test_editor_can_save(mock_systemctl, mock_reload, mock_execute, mock_db):
    from api.routes import save_file

    role = "editor"
    mock_systemctl.return_value = "Active: active (running)"
    # execute_command is called for: 1) tee write, 2) stat -c %Y
    mock_execute.side_effect = ["", "1709827200\n"]

    # Mock DB for the collision avoidance UPDATE
    conn_mock = AsyncMock()
    conn_mock.execute = AsyncMock()
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__.return_value = conn_mock

    response = await save_file(
        request=MagicMock(),
        server_id=1,
        file_path="/fake/path",
        scope="user",
        unit_name="fake.service",
        content="data",
        role=role
    )
    assert response.status_code == 200
    assert "Saved" in response.body.decode()


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
async def test_editor_can_create(mock_execute, mock_db):
    from api.routes import create_new_quadlet

    role = "editor"
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = ("[Container]\n",)

    cursor_context_mock = AsyncMock()
    cursor_context_mock.__aenter__.return_value = mock_cursor

    conn_mock = AsyncMock()
    conn_mock.execute = MagicMock(return_value=cursor_context_mock)
    mock_db.return_value.__aenter__.return_value = conn_mock

    response = await create_new_quadlet(
        request=MagicMock(),
        server_id=1,
        scope="user",
        type="container",
        name="test",
        role=role
    )
    assert response.status_code == 200
    assert "Created" in response.body.decode()
    assert response.headers.get("HX-Trigger") == "reload-servers"


@pytest.mark.asyncio
@patch('api.routes.systemctl_action', new_callable=AsyncMock)
async def test_editor_can_systemctl_post(mock_action):
    from api.routes import api_systemctl_post

    role = "editor"
    mock_action.return_value = "fake result"

    response = await api_systemctl_post(
        server_id=1,
        action="start",
        unit="fake.service",
        scope="user",
        role=role
    )
    assert response.status_code == 200
    assert "fake result" in response.body.decode()


# =============================================================================
# Test quadlet syntax validation on save
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
async def test_save_invalid_container_returns_validation_error(mock_execute):
    """Saving a .container file with invalid content must return an error toast
    without calling execute_command (file must not be written)."""
    from api.routes import save_file

    invalid_content = "[Container]\n# Missing required Image key\nNetwork=host\n"

    response = await save_file(
        request=MagicMock(),
        server_id=1,
        file_path="/etc/containers/systemd/myapp.container",
        scope="user",
        unit_name="myapp.service",
        content=invalid_content,
        role="editor"
    )

    body = response.body.decode()
    assert "Validation error" in body
    assert "toast-red" in body
    mock_execute.assert_not_called()


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@patch('api.routes.reload_and_restart', new_callable=AsyncMock)
@patch('api.routes.systemctl_action', new_callable=AsyncMock)
async def test_save_valid_container_proceeds(mock_systemctl, mock_reload, mock_execute, mock_db):
    """Saving a .container file with valid content must write the file."""
    from api.routes import save_file

    valid_content = "[Container]\nImage=nginx:latest\nNetwork=host\n"
    mock_systemctl.return_value = "Active: active (running)"
    mock_execute.side_effect = ["", "1709827200\n"]

    conn_mock = AsyncMock()
    conn_mock.execute = AsyncMock()
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__.return_value = conn_mock

    response = await save_file(
        request=MagicMock(),
        server_id=1,
        file_path="/etc/containers/systemd/myapp.container",
        scope="user",
        unit_name="myapp.service",
        content=valid_content,
        role="editor"
    )

    body = response.body.decode()
    assert "Saved" in body
    mock_execute.assert_called()
