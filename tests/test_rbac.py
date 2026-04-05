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


# =============================================================================
# Test admin API navigator refresh (issue #35)
# =============================================================================

class _AioDualMock:
    """Supports both `await db.execute(...)` and `async with db.execute(...) as cur:`."""
    def __init__(self, fetchone_result=None):
        self._result = fetchone_result

    def __await__(self):
        async def _noop(): pass
        return _noop().__await__()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def fetchone(self):
        return self._result


@pytest.mark.asyncio
@patch('api.routes.encrypt_private_key', return_value=b'encrypted')
@patch('api.routes.settings_list_servers', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
async def test_add_server_triggers_navigator_refresh(mock_db, mock_list_servers, mock_encrypt):
    from fastapi.responses import HTMLResponse
    from api.routes import settings_add_server

    mock_list_servers.return_value = HTMLResponse("<table></table>")

    _insert = _AioDualMock()
    _select = _AioDualMock(fetchone_result=(1,))

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(side_effect=[_insert, _select, _insert])
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    response = await settings_add_server(
        request=MagicMock(),
        name="test-server",
        ip_address="192.168.1.1",
        ssh_user="ubuntu",
        key_name="my-key",
        private_key="-----BEGIN OPENSSH PRIVATE KEY-----",
        scope_filter="both",
        role="editor",
        is_admin=True,
    )
    assert response.headers.get("HX-Trigger") == "reload-servers"


@pytest.mark.asyncio
@patch('api.routes.pool')
@patch('api.routes.settings_list_servers', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
async def test_delete_server_triggers_navigator_refresh(mock_db, mock_list_servers, mock_pool):
    from fastapi.responses import HTMLResponse
    from api.routes import settings_delete_server

    mock_list_servers.return_value = HTMLResponse("<table></table>")

    _select_key = _AioDualMock(fetchone_result=(1,))    # ssh_key_id = 1
    _delete_server = _AioDualMock()
    _select_count = _AioDualMock(fetchone_result=(0,))  # no other servers use key
    _delete_key = _AioDualMock()

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(side_effect=[
        _select_key, _delete_server, _select_count, _delete_key,
    ])
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    response = await settings_delete_server(
        request=MagicMock(),
        server_id=1,
        role="editor",
        is_admin=True,
    )
    assert response.headers.get("HX-Trigger") == "reload-servers"


@pytest.mark.asyncio
@patch('api.routes.encrypt_private_key', return_value=b'encrypted')
@patch('api.routes.settings_list_servers', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
async def test_viewer_cannot_add_server(mock_db, mock_list_servers, mock_encrypt):
    from api.routes import settings_add_server

    with pytest.raises(HTTPException) as exc_info:
        await settings_add_server(
            request=MagicMock(),
            name="test-server",
            ip_address="192.168.1.1",
            ssh_user="ubuntu",
            key_name="my-key",
            private_key="key",
            role="viewer",
            is_admin=False,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@patch('api.routes.pool')
@patch('api.routes.settings_list_servers', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
async def test_viewer_cannot_delete_server(mock_db, mock_list_servers, mock_pool):
    from api.routes import settings_delete_server

    with pytest.raises(HTTPException) as exc_info:
        await settings_delete_server(
            request=MagicMock(),
            server_id=1,
            role="viewer",
            is_admin=False,
        )
    assert exc_info.value.status_code == 403


# =============================================================================
# Test admin role: server management
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.encrypt_private_key', return_value=b'encrypted')
@patch('api.routes.settings_list_servers', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
async def test_non_admin_editor_cannot_add_server(mock_db, mock_list_servers, mock_encrypt):
    from api.routes import settings_add_server

    with pytest.raises(HTTPException) as exc_info:
        await settings_add_server(
            request=MagicMock(),
            name="test-server",
            ip_address="1.2.3.4",
            ssh_user="ubuntu",
            key_name="key",
            private_key="pem",
            role="editor",
            is_admin=False,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@patch('api.routes.pool')
@patch('api.routes.settings_list_servers', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
async def test_non_admin_editor_cannot_delete_server(mock_db, mock_list_servers, mock_pool):
    from api.routes import settings_delete_server

    with pytest.raises(HTTPException) as exc_info:
        await settings_delete_server(
            request=MagicMock(),
            server_id=1,
            role="editor",
            is_admin=False,
        )
    assert exc_info.value.status_code == 403


# =============================================================================
# Test admin role: user management
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_non_admin_editor_cannot_list_users(mock_db):
    from api.routes import settings_list_users

    response = await settings_list_users(
        request=MagicMock(),
        role="editor",
        is_admin=False,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_non_admin_editor_cannot_add_user(mock_db):
    from api.routes import settings_add_user

    with pytest.raises(HTTPException) as exc_info:
        await settings_add_user(
            request=MagicMock(),
            username="newuser",
            password="pass",
            user_role="viewer",
            role="editor",
            is_admin=False,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_non_admin_editor_cannot_update_user_role(mock_db):
    from api.routes import settings_update_user_role

    with pytest.raises(HTTPException) as exc_info:
        await settings_update_user_role(
            request=MagicMock(),
            user_id=2,
            user_role="editor",
            role="editor",
            is_admin=False,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_non_admin_editor_cannot_delete_user(mock_db):
    from api.routes import settings_delete_user

    with pytest.raises(HTTPException) as exc_info:
        await settings_delete_user(
            request=MagicMock(),
            user_id=2,
            role="editor",
            is_admin=False,
        )
    assert exc_info.value.status_code == 403


# =============================================================================
# Test admin role: server update (PUT)
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.settings_list_servers', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
async def test_admin_can_update_server(mock_db, mock_list_servers):
    from fastapi.responses import HTMLResponse
    from api.routes import settings_update_server

    mock_list_servers.return_value = HTMLResponse("<table></table>")

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(return_value=_AioDualMock())
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    response = await settings_update_server(
        request=MagicMock(),
        server_id=1,
        name="updated-name",
        ip_address="10.0.0.1",
        ssh_user="ubuntu",
        scope_filter="both",
        role="editor",
        is_admin=True,
    )
    assert response.headers.get("HX-Trigger") == "reload-servers"


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_non_admin_editor_cannot_update_server(mock_db):
    from api.routes import settings_update_server

    with pytest.raises(HTTPException) as exc_info:
        await settings_update_server(
            request=MagicMock(),
            server_id=1,
            name="updated-name",
            ip_address="10.0.0.1",
            ssh_user="ubuntu",
            role="editor",
            is_admin=False,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_viewer_cannot_update_server(mock_db):
    from api.routes import settings_update_server

    with pytest.raises(HTTPException) as exc_info:
        await settings_update_server(
            request=MagicMock(),
            server_id=1,
            name="updated-name",
            ip_address="10.0.0.1",
            ssh_user="ubuntu",
            role="viewer",
            is_admin=False,
        )
    assert exc_info.value.status_code == 403


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


# =============================================================================
# Test admin promotion/demotion
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.settings_list_users', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
async def test_admin_can_promote_user(mock_db, mock_list_users):
    from fastapi.responses import HTMLResponse
    from api.routes import settings_toggle_admin

    mock_list_users.return_value = HTMLResponse("<table></table>")

    _select = _AioDualMock(fetchone_result=("other_user",))
    _update = _AioDualMock()

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(side_effect=[_select, _update])
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    request = MagicMock()
    request.cookies.get.return_value = None
    with patch('api.routes._get_session', new_callable=AsyncMock, return_value={"username": "admin", "role": "editor", "is_admin": True}):
        response = await settings_toggle_admin(
            request=request,
            user_id=2,
            is_admin_target=True,
            role="editor",
            is_admin=True,
        )
    assert response.status_code == 200


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_admin_cannot_demote_self(mock_db):
    from api.routes import settings_toggle_admin

    _select = _AioDualMock(fetchone_result=("admin",))

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(return_value=_select)
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    request = MagicMock()
    with patch('api.routes._get_session', new_callable=AsyncMock, return_value={"username": "admin", "role": "editor", "is_admin": True}):
        response = await settings_toggle_admin(
            request=request,
            user_id=1,
            is_admin_target=False,
            role="editor",
            is_admin=True,
        )
    assert response.status_code == 400


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_non_admin_cannot_toggle_admin(mock_db):
    from api.routes import settings_toggle_admin

    with pytest.raises(HTTPException) as exc_info:
        await settings_toggle_admin(
            request=MagicMock(),
            user_id=2,
            is_admin_target=True,
            role="editor",
            is_admin=False,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@patch('api.routes.settings_list_users', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
async def test_admin_can_create_admin_user(mock_db, mock_list_users):
    from fastapi.responses import HTMLResponse
    from api.routes import settings_add_user

    mock_list_users.return_value = HTMLResponse("<table></table>")

    conn_mock = AsyncMock()
    conn_mock.execute = AsyncMock()
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__.return_value = conn_mock

    request = MagicMock()
    with patch('api.routes._get_session', new_callable=AsyncMock, return_value={"username": "admin", "role": "editor", "is_admin": True}):
        response = await settings_add_user(
            request=request,
            username="newadmin",
            password="secret",
            user_role="editor",
            new_is_admin=True,
            role="editor",
            is_admin=True,
        )
    assert response.status_code == 200
