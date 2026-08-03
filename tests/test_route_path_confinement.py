"""Route-level tests pinning the path-confinement guard (issue #289, part 2).

Each of fetch_file, save_file, delete_file, and create_new_quadlet must reject
a caller-supplied path/name that escapes the quadlet directory for the given
scope with HTTPException(400) *before* the escaping path ever reaches
pool.execute_command. A 400 raised only after the shell command already ran
would not be a fix, so every test here checks both things: the exception and
that execute_command was never called with the escaping path.
"""
import os
import sys

import pytest
from fastapi import HTTPException
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

TRAVERSAL_PATH = "/etc/containers/systemd/../../etc/shadow"


def _assert_execute_command_never_called_with(mock_execute, needle: str):
    for call in mock_execute.call_args_list:
        for arg in call.args:
            assert needle not in str(arg), (
                f"execute_command was called with the escaping path: {call}"
            )


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_delete_file_rejects_dotdot_traversal_before_running_rm(mock_execute, mock_db):
    from api.routes import delete_file

    mock_execute.return_value = ""
    conn_mock = AsyncMock()
    conn_mock.execute = AsyncMock()
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__.return_value = conn_mock

    request = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await delete_file(
            request=request,
            server_id=1,
            path=TRAVERSAL_PATH,
            scope="global",
            role="editor"
        )

    assert exc_info.value.status_code == 400
    _assert_execute_command_never_called_with(mock_execute, "shadow")


@pytest.mark.asyncio
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_fetch_file_rejects_dotdot_traversal_before_running_cat(mock_execute):
    from api.routes import fetch_file

    mock_execute.return_value = "root:x:0:0::/root:/bin/bash"

    request = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await fetch_file(
            request=request,
            server_id=1,
            path=TRAVERSAL_PATH,
            scope="global",
            name="shadow",
            role="editor"
        )

    assert exc_info.value.status_code == 400
    _assert_execute_command_never_called_with(mock_execute, "shadow")


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@patch('api.routes.reload_and_restart', new_callable=AsyncMock)
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_save_file_rejects_dotdot_traversal_before_writing(mock_execute, mock_reload, mock_db):
    from api.routes import save_file

    mock_execute.return_value = ""
    conn_mock = AsyncMock()
    conn_mock.execute = AsyncMock()
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__.return_value = conn_mock

    request = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await save_file(
            request=request,
            server_id=1,
            file_path=TRAVERSAL_PATH,
            scope="global",
            unit_name="shadow.service",
            content="malicious content",
            role="editor"
        )

    assert exc_info.value.status_code == 400
    _assert_execute_command_never_called_with(mock_execute, "shadow")


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_create_file_rejects_traversal_in_name_before_writing(mock_execute, mock_db):
    from api.routes import create_new_quadlet

    mock_execute.return_value = "/home/test"
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = ("[Container]\n",)

    cursor_context_mock = AsyncMock()
    cursor_context_mock.__aenter__.return_value = mock_cursor

    conn_mock = AsyncMock()
    conn_mock.execute = MagicMock(return_value=cursor_context_mock)
    mock_db.return_value.__aenter__.return_value = conn_mock

    request = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await create_new_quadlet(
            request=request,
            server_id=1,
            scope="global",
            quadlet_type="container",
            name="../../../tmp/evil",
            role="editor"
        )

    assert exc_info.value.status_code == 400
    _assert_execute_command_never_called_with(mock_execute, "evil")
