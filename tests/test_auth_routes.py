import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app
import hashlib

@pytest.fixture
def client():
    # Make sure DEV_AUTO_LOGIN is disabled for these tests
    with patch("core.config_loader.global_config.dev_auto_login", False):
        yield TestClient(app)

@pytest.fixture
def mock_db_login():
    with patch("api.routes.get_db_connection") as mock_conn:
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        
        # User details: password_hash, role, is_admin
        pwd_hash = hashlib.sha256(b"password123").hexdigest()
        mock_cursor.fetchone.return_value = (pwd_hash, "admin", 1)
        
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def _mock_execute(*args):
            yield mock_cursor
            
        mock_db.execute = _mock_execute
        
        @asynccontextmanager
        async def _mock_conn():
            yield mock_db
            
        mock_conn.side_effect = _mock_conn
        yield mock_cursor

def test_login_page_unauthenticated(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Login" in response.text

def test_login_submit_success(client, mock_db_login):
    response = client.post("/login", data={"username": "admin", "password": "password123"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "qm_session" in response.cookies

def test_login_submit_invalid_password(client, mock_db_login):
    response = client.post("/login", data={"username": "admin", "password": "wrong_password"}, follow_redirects=False)
    assert response.status_code == 401
    assert "Invalid username or password" in response.text

def test_login_submit_unknown_user(client, mock_db_login):
    mock_db_login.fetchone.return_value = None
    response = client.post("/login", data={"username": "unknown", "password": "password123"}, follow_redirects=False)
    assert response.status_code == 401
    assert "Invalid username or password" in response.text

def test_logout(client, mock_db_login):
    # Get cookie
    response = client.post("/login", data={"username": "admin", "password": "password123"}, follow_redirects=False)
    cookie = response.cookies["qm_session"]
    
    # Logout
    logout_resp = client.get("/logout", cookies={"qm_session": cookie}, follow_redirects=False)
    assert logout_resp.status_code == 303
    assert logout_resp.headers["location"] == "/login"

def test_access_dashboard_unauthenticated(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

def test_login_page_redirects_when_authenticated(client, mock_db_login):
    response = client.post("/login", data={"username": "admin", "password": "password123"}, follow_redirects=False)
    cookie = response.cookies["qm_session"]
    
    # Try accessing /login again
    resp = client.get("/login", cookies={"qm_session": cookie}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

def test_invalid_session_cookie(client):
    # Fake/tampered cookie
    resp = client.get("/", cookies={"qm_session": "bad_cookie"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
