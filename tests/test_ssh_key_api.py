"""Tests for SSH Key Management API endpoints (issue #33)."""
import sys
import os
import pytest
from fastapi import HTTPException
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class _AioDualMock:
    """Supports both `await db.execute(...)` and `async with db.execute(...) as cur:`."""
    def __init__(self, fetchone_result=None, fetchall_result=None):
        self._fetchone = fetchone_result
        self._fetchall = fetchall_result or []

    def __await__(self):
        async def _noop(): pass
        return _noop().__await__()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def fetchone(self):
        return self._fetchone

    async def fetchall(self):
        return self._fetchall


# =============================================================================
# GET /api/keys
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_non_admin_cannot_list_keys(mock_db):
    from api.routes import api_list_keys

    response = await api_list_keys(
        request=MagicMock(),
        is_admin=False,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_admin_can_list_keys(mock_db):
    from api.routes import api_list_keys

    _select = _AioDualMock(fetchall_result=[(1, "my-key"), (2, "deploy-key")])

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(return_value=_select)
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    response = await api_list_keys(
        request=MagicMock(),
        is_admin=True,
    )
    assert response.status_code == 200
    body = response.body.decode()
    assert "my-key" in body
    assert "deploy-key" in body


# =============================================================================
# POST /api/keys
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@patch('api.routes.encrypt_private_key', return_value=b'encrypted')
async def test_non_admin_cannot_add_key(mock_encrypt, mock_db):
    from api.routes import api_add_key

    with pytest.raises(HTTPException) as exc_info:
        await api_add_key(
            request=MagicMock(),
            key_name="test-key",
            private_key="-----BEGIN OPENSSH PRIVATE KEY-----",
            key_file=None,
            is_admin=False,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@patch('api.routes.api_list_keys', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
@patch('api.routes.encrypt_private_key', return_value=b'encrypted')
async def test_admin_can_add_key_by_paste(mock_encrypt, mock_db, mock_list):
    from fastapi.responses import HTMLResponse
    from api.routes import api_add_key

    mock_list.return_value = HTMLResponse("<table></table>")

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(return_value=_AioDualMock())
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    response = await api_add_key(
        request=MagicMock(),
        key_name="my-key",
        private_key="-----BEGIN OPENSSH PRIVATE KEY-----\ndata\n-----END OPENSSH PRIVATE KEY-----",
        key_file=None,
        is_admin=True,
    )
    assert response.status_code == 200
    mock_encrypt.assert_called_once()


@pytest.mark.asyncio
@patch('api.routes.api_list_keys', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
@patch('api.routes.encrypt_private_key', return_value=b'encrypted')
async def test_admin_can_add_key_by_file_upload(mock_encrypt, mock_db, mock_list):
    from fastapi.responses import HTMLResponse
    from api.routes import api_add_key

    mock_list.return_value = HTMLResponse("<table></table>")

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(return_value=_AioDualMock())
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    fake_file = AsyncMock()
    fake_file.read = AsyncMock(return_value=b"-----BEGIN OPENSSH PRIVATE KEY-----\ndata\n-----END OPENSSH PRIVATE KEY-----")

    response = await api_add_key(
        request=MagicMock(),
        key_name="upload-key",
        private_key="",
        key_file=fake_file,
        is_admin=True,
    )
    assert response.status_code == 200
    mock_encrypt.assert_called_once()


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@patch('api.routes.encrypt_private_key', return_value=b'encrypted')
async def test_add_key_requires_key_content(mock_encrypt, mock_db):
    """POST with no paste and no file must return 400."""
    from api.routes import api_add_key

    with pytest.raises(HTTPException) as exc_info:
        await api_add_key(
            request=MagicMock(),
            key_name="my-key",
            private_key="",
            key_file=None,
            is_admin=True,
        )
    assert exc_info.value.status_code == 400


# =============================================================================
# DELETE /api/keys/{key_id}
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_non_admin_cannot_delete_key(mock_db):
    from api.routes import api_delete_key

    with pytest.raises(HTTPException) as exc_info:
        await api_delete_key(
            request=MagicMock(),
            key_id=1,
            is_admin=False,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@patch('api.routes.api_list_keys', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
async def test_admin_can_delete_key(mock_db, mock_list):
    from fastapi.responses import HTMLResponse
    from api.routes import api_delete_key

    mock_list.return_value = HTMLResponse("<table></table>")

    _check = _AioDualMock(fetchone_result=(0,))   # no servers reference this key
    _delete = _AioDualMock()

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(side_effect=[_check, _delete])
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    response = await api_delete_key(
        request=MagicMock(),
        key_id=1,
        is_admin=True,
    )
    assert response.status_code == 200


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_delete_key_in_use_returns_409(mock_db):
    """Deleting a key that is still referenced by a server must return 409."""
    from api.routes import api_delete_key

    _check = _AioDualMock(fetchone_result=(2,))   # 2 servers reference this key

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(return_value=_check)
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    with pytest.raises(HTTPException) as exc_info:
        await api_delete_key(
            request=MagicMock(),
            key_id=1,
            is_admin=True,
        )
    assert exc_info.value.status_code == 409
