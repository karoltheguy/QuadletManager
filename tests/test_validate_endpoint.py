"""Tests for the /api/validate/{server_id} endpoint (RED phase).

These tests exercise api.routes.validate_quadlet directly by awaiting it
with kwargs, patching collaborators in the api.routes namespace, following
the pattern established in tests/test_rbac.py.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from services.ssh_manager import SSHCommandError


@pytest.mark.asyncio
@pytest.mark.unit
@patch('api.routes.validate_remote', new_callable=AsyncMock)
async def test_validate_endpoint_happy_path(mock_validate_remote):
    from api.routes import validate_quadlet

    verdict = {"valid": True, "local_only": False, "issues": []}
    mock_validate_remote.return_value = verdict

    response = await validate_quadlet(
        server_id=1,
        file_path="/etc/containers/systemd/test.container",
        scope="system",
        content="[Container]\nImage=quay.io/x\n",
        role="editor",
    )

    assert response.status_code == 200
    assert json.loads(response.body) == verdict

    mock_validate_remote.assert_awaited_once_with(
        1,
        "[Container]\nImage=quay.io/x\n",
        "test.container",
        "system",
    )


@pytest.mark.asyncio
@pytest.mark.unit
@patch('api.routes.validate_remote', new_callable=AsyncMock)
async def test_validate_endpoint_issues_propagate(mock_validate_remote):
    from api.routes import validate_quadlet

    verdict = {
        "valid": False,
        "local_only": False,
        "issues": [{"level": "error", "message": "boom", "key": None}],
    }
    mock_validate_remote.return_value = verdict

    response = await validate_quadlet(
        server_id=1,
        file_path="/etc/containers/systemd/test.container",
        scope="system",
        content="[Container]\nImage=quay.io/x\n",
        role="editor",
    )

    assert response.status_code == 200
    assert json.loads(response.body) == verdict


@pytest.mark.asyncio
@pytest.mark.unit
@patch('api.routes.validate_remote', new_callable=AsyncMock)
async def test_validate_endpoint_ssh_failure_returns_502(mock_validate_remote):
    from api.routes import validate_quadlet

    mock_validate_remote.side_effect = SSHCommandError("connection refused")

    response = await validate_quadlet(
        server_id=1,
        file_path="/etc/containers/systemd/test.container",
        scope="system",
        content="[Container]\nImage=quay.io/x\n",
        role="editor",
    )

    assert response.status_code == 502
    body = json.loads(response.body)
    assert isinstance(body.get("error"), str)


@pytest.mark.asyncio
@pytest.mark.unit
@patch('api.routes.validate_remote', new_callable=AsyncMock)
async def test_validate_endpoint_ssh_failure_no_stack_trace_leak(mock_validate_remote):
    from api.routes import validate_quadlet

    mock_validate_remote.side_effect = SSHCommandError("SENTINEL_LEAK_/etc/secret/path")

    response = await validate_quadlet(
        server_id=1,
        file_path="/etc/containers/systemd/test.container",
        scope="system",
        content="[Container]\nImage=quay.io/x\n",
        role="editor",
    )

    assert response.status_code == 502
    body = json.loads(response.body)
    assert isinstance(body.get("error"), str)
    assert "SENTINEL_LEAK_/etc/secret/path" not in response.body.decode()


@pytest.mark.asyncio
@pytest.mark.unit
@patch('api.routes.validate_remote', new_callable=AsyncMock)
async def test_validate_endpoint_viewer_forbidden(mock_validate_remote):
    from api.routes import validate_quadlet

    mock_validate_remote.return_value = {"valid": True, "local_only": False, "issues": []}

    with pytest.raises(HTTPException) as exc_info:
        await validate_quadlet(
            server_id=1,
            file_path="/etc/containers/systemd/test.container",
            scope="system",
            content="[Container]\nImage=quay.io/x\n",
            role="viewer",
        )

    assert exc_info.value.status_code == 403

    mock_validate_remote.assert_not_awaited()
