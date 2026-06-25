import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app

@pytest.fixture
def client():
    with patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as test_client:
            yield test_client

def test_api_quadlets_db_error(client):
    with patch("api.routes.get_db_connection") as mock_conn:
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def _mock_conn():
            raise Exception("DB Error")
            yield
        mock_conn.side_effect = _mock_conn
        
        response = client.get("/api/quadlets/1")
        assert response.status_code == 200
        assert "Error loading files" in response.text

def test_api_reorder_servers_invalid_order_format(client):
    response = client.patch("/api/settings/servers/reorder", json={"order": "not a list"})
    assert response.status_code == 422
    assert "'order' must be a list of integer server IDs" in response.text

def test_api_reorder_servers_invalid_order_content(client):
    response = client.patch("/api/settings/servers/reorder", json={"order": ["1", "2"]})
    assert response.status_code == 422
    assert "'order' must be a list of integer server IDs" in response.text

def test_api_reorder_servers_missing_servers(client):
    with patch("api.routes.get_db_connection") as mock_conn:
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [(1,), (2,)]
        
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def _mock_execute(*args):
            yield mock_cursor
            
        mock_db.execute = _mock_execute
        
        @asynccontextmanager
        async def _mock_conn():
            yield mock_db
            
        mock_conn.side_effect = _mock_conn
        
        response = client.patch("/api/settings/servers/reorder", json={"order": [1]})
        assert response.status_code == 422
        assert "'order' must contain every server ID exactly once" in response.text



def test_api_file_db_error(client):
    with patch("api.routes.get_db_connection") as mock_conn:
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def _mock_conn():
            raise Exception("DB Error")
            yield
        mock_conn.side_effect = _mock_conn
        
        response = client.get("/api/file/1?path=test&scope=user&name=test")
        assert response.status_code == 200
        assert "Failed to load file content" in response.text

def test_api_save_exception(client):
    with patch("api.routes.pool.execute_command") as mock_exec:
        mock_exec.side_effect = Exception("SSH Error")
        response = client.post("/api/save", data={"server_id": 1, "file_path": "test", "scope": "user", "unit_name": "test", "content": "data"}, follow_redirects=False)
        assert response.status_code == 200
        assert "Failed to save" in response.text

def test_api_systemctl_status_exception(client):
    with patch("api.routes.systemctl_action") as mock_action:
        mock_action.side_effect = Exception("Status Error")
        response = client.get("/api/systemctl/status/1?unit=test&scope=user", follow_redirects=False)
        assert response.status_code == 200
        assert "Status Error" in response.text

def test_api_systemctl_post_exception(client):
    with patch("api.routes.systemctl_action") as mock_action:
        mock_action.side_effect = Exception("Action Error")
        # Action needs to be start/stop/restart/status, role is editor by default for TestClient if we mock it? Wait, we're not mocking auth here, but TestClient with dev_auto_login=True uses 'editor'.
        response = client.post("/api/systemctl/1", params={"action": "start", "unit": "test", "scope": "user"}, follow_redirects=False)
        assert response.status_code == 200
        assert "Action failed" in response.text

def test_api_pod_action_exception(client):
    with patch("api.routes.pool.execute_command") as mock_exec:
        mock_exec.side_effect = Exception("Pod Error")
        response = client.post("/api/pod-action/1", params={"action": "start", "pod_name": "test", "scope": "user"}, follow_redirects=False)
        assert response.status_code == 200
        assert "Pod action failed" in response.text

def test_api_activity_exception(client):
    with patch("api.routes.get_container_activity") as mock_act:
        mock_act.side_effect = Exception("Activity Error")
        response = client.get("/api/activity/1?container=test", follow_redirects=False)
        assert response.status_code == 500
        assert "Failed to fetch activity" in response.text

def test_api_create_exception(client):
    with patch("api.routes.pool.execute_command") as mock_exec:
        mock_exec.side_effect = Exception("Create Error")
        response = client.post("/api/create", data={"server_id": 1, "scope": "user", "type": "container", "name": "test"}, follow_redirects=False)
        assert response.status_code == 200
        assert "Creation Failed" in response.text

