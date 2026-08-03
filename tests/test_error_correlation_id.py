import re
import logging
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app
from services.ssh_manager import SSHCommandError

REF_RE = re.compile(r"\(ref: ([0-9a-f]{6})\)")
SENTINEL = "SENTINEL_LEAK_/etc/secret"


@pytest.fixture
def client():
    with patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as test_client:
            yield test_client


@pytest.mark.unit
def test_save_error_has_correlation_id_and_logs_exception(client, caplog):
    with caplog.at_level(logging.ERROR, logger="quadlet-manager.routes"):
        with patch("api.routes.pool.execute_command") as mock_exec:
            mock_exec.side_effect = Exception(SENTINEL)
            response = client.post(
                "/api/save",
                data={"server_id": 1, "file_path": "/home/quadlet/.config/containers/systemd/myapp", "scope": "user", "unit_name": "test", "content": "data"},
                follow_redirects=False,
            )
    assert response.status_code == 200
    assert SENTINEL not in response.text

    match = REF_RE.search(response.text)
    assert match, f"Expected a (ref: xxxxxx) correlation id in response, got: {response.text}"
    ref = match.group(1)
    assert ref in caplog.text
    assert SENTINEL in caplog.text


@pytest.mark.unit
def test_create_error_has_correlation_id_and_logs_exception(client, caplog):
    with caplog.at_level(logging.ERROR, logger="quadlet-manager.routes"):
        with patch("api.routes.pool.execute_command") as mock_exec:
            mock_exec.side_effect = Exception(SENTINEL)
            response = client.post(
                "/api/create",
                data={"server_id": 1, "scope": "user", "type": "container", "name": "test"},
                follow_redirects=False,
            )
    assert response.status_code == 200
    assert SENTINEL not in response.text

    match = REF_RE.search(response.text)
    assert match, f"Expected a (ref: xxxxxx) correlation id in response, got: {response.text}"
    ref = match.group(1)
    assert ref in caplog.text
    assert SENTINEL in caplog.text


@pytest.mark.unit
def test_delete_error_has_correlation_id_and_logs_exception(client, caplog):
    with caplog.at_level(logging.ERROR, logger="quadlet-manager.routes"):
        with patch("api.routes.pool.execute_command") as mock_exec:
            mock_exec.side_effect = Exception(SENTINEL)
            response = client.request(
                "DELETE",
                "/api/files",
                params={"server_id": 1, "path": "/home/quadlet/.config/containers/systemd/test.container", "scope": "user"},
                follow_redirects=False,
            )
    assert response.status_code == 200
    assert SENTINEL not in response.text

    match = REF_RE.search(response.text)
    assert match, f"Expected a (ref: xxxxxx) correlation id in response, got: {response.text}"
    ref = match.group(1)
    assert ref in caplog.text
    assert SENTINEL in caplog.text


@pytest.mark.unit
def test_validate_error_has_correlation_id_and_logs_exception(client, caplog):
    with caplog.at_level(logging.ERROR, logger="quadlet-manager.routes"):
        with patch("api.routes.validate_remote") as mock_validate:
            mock_validate.side_effect = SSHCommandError(SENTINEL)
            response = client.post(
                "/api/validate/1",
                data={"file_path": "test.container", "scope": "user", "content": "data"},
                follow_redirects=False,
            )
    assert response.status_code == 502
    assert SENTINEL not in response.text

    match = REF_RE.search(response.text)
    assert match, f"Expected a (ref: xxxxxx) correlation id in response, got: {response.text}"
    ref = match.group(1)
    assert ref in caplog.text
    assert SENTINEL in caplog.text


@pytest.mark.unit
def test_systemctl_status_error_has_correlation_id_and_logs_exception(client, caplog):
    with caplog.at_level(logging.ERROR, logger="quadlet-manager.routes"):
        with patch("api.routes.systemctl_action") as mock_action:
            mock_action.side_effect = Exception(SENTINEL)
            response = client.get(
                "/api/systemctl/status/1?unit=test&scope=user",
                follow_redirects=False,
            )
    assert response.status_code == 200
    assert SENTINEL not in response.text

    match = REF_RE.search(response.text)
    assert match, f"Expected a (ref: xxxxxx) correlation id in response, got: {response.text}"
    ref = match.group(1)
    assert ref in caplog.text
    assert SENTINEL in caplog.text


@pytest.mark.unit
def test_save_error_correlation_id_is_random_per_request(client, caplog):
    with caplog.at_level(logging.ERROR, logger="quadlet-manager.routes"):
        with patch("api.routes.pool.execute_command") as mock_exec:
            mock_exec.side_effect = Exception(SENTINEL)
            response1 = client.post(
                "/api/save",
                data={"server_id": 1, "file_path": "/home/quadlet/.config/containers/systemd/myapp", "scope": "user", "unit_name": "test", "content": "data"},
                follow_redirects=False,
            )
            response2 = client.post(
                "/api/save",
                data={"server_id": 1, "file_path": "/home/quadlet/.config/containers/systemd/myapp", "scope": "user", "unit_name": "test", "content": "data"},
                follow_redirects=False,
            )

    match1 = REF_RE.search(response1.text)
    match2 = REF_RE.search(response2.text)
    assert match1, f"Expected a (ref: xxxxxx) correlation id in response, got: {response1.text}"
    assert match2, f"Expected a (ref: xxxxxx) correlation id in response, got: {response2.text}"
    assert match1.group(1) != match2.group(1)
