"""Tests for DELETE /api/files endpoint (issue #36)."""
import sys
import os
import pytest
from fastapi import HTTPException
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# =============================================================================
# RBAC: viewer cannot delete
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.unit
async def test_viewer_cannot_delete_file():
    from api.routes import delete_file

    request = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        await delete_file(
            request=request,
            server_id=1,
            path="/home/user/.config/containers/systemd/myapp.container",
            scope="user",
            role="viewer"
        )

    assert exc_info.value.status_code == 403
    assert "cannot delete" in exc_info.value.detail


# =============================================================================
# Editor: user-scope deletion (no sudo)
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_editor_can_delete_user_scope_file(mock_execute, mock_db):
    from api.routes import delete_file

    mock_execute.return_value = ""
    conn_mock = AsyncMock()
    conn_mock.execute = AsyncMock()
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__.return_value = conn_mock

    response = await delete_file(
        request=MagicMock(),
        server_id=1,
        path="/home/user/.config/containers/systemd/myapp.container",
        scope="user",
        role="editor"
    )

    assert response.status_code == 200
    assert "Deleted" in response.body.decode()

    # rm command must NOT use sudo for user scope
    cmd = mock_execute.call_args[0][1]
    assert "sudo" not in cmd
    assert "rm" in cmd


# =============================================================================
# Editor: global-scope deletion (sudo required)
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_editor_can_delete_global_scope_file(mock_execute, mock_db):
    from api.routes import delete_file

    mock_execute.return_value = ""
    conn_mock = AsyncMock()
    conn_mock.execute = AsyncMock()
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__.return_value = conn_mock

    response = await delete_file(
        request=MagicMock(),
        server_id=1,
        path="/etc/containers/systemd/myapp.container",
        scope="global",
        role="editor"
    )

    assert response.status_code == 200
    assert "Deleted" in response.body.decode()

    # rm command must use sudo for global scope
    cmd = mock_execute.call_args[0][1]
    assert "sudo" in cmd
    assert "rm" in cmd


# =============================================================================
# Successful deletion triggers navigator refresh
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_delete_triggers_navigator_refresh(mock_execute, mock_db):
    from api.routes import delete_file

    mock_execute.return_value = ""
    conn_mock = AsyncMock()
    conn_mock.execute = AsyncMock()
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__.return_value = conn_mock

    response = await delete_file(
        request=MagicMock(),
        server_id=1,
        path="/home/user/.config/containers/systemd/myapp.container",
        scope="user",
        role="editor"
    )

    assert response.headers.get("HX-Trigger") == "reload-servers"


# =============================================================================
# SSH error returns error toast (not 500)
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_delete_ssh_error_returns_error_toast(mock_execute):
    from api.routes import delete_file

    mock_execute.side_effect = Exception("Connection refused")

    response = await delete_file(
        request=MagicMock(),
        server_id=1,
        path="/home/user/.config/containers/systemd/myapp.container",
        scope="user",
        role="editor"
    )

    assert response.status_code == 200
    body = response.body.decode()
    assert "toast-red" in body
    assert "Failed" in body
