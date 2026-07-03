import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from contextlib import asynccontextmanager
from fastapi.testclient import TestClient
from main import app
import hashlib
from argon2 import PasswordHasher

@pytest.fixture
def client():
    # Make sure DEV_AUTO_LOGIN is disabled for these tests
    with patch("core.config_loader.global_config.dev_auto_login", False):
        with TestClient(app) as test_client:
            yield test_client

@pytest.fixture
def mock_db_login():
    with patch("api.routes.get_db_connection") as mock_conn:
        pwd_hash = PasswordHasher().hash("password123")
        
        class MockCursor:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                pass
            def __await__(self):
                async def _aw():
                    return self
                return _aw().__await__()
            async def fetchone(self):
                # Return None if it's the unknown user test, else the admin user
                return getattr(self, "return_value", (pwd_hash, "admin", 1))

        mock_cursor = MockCursor()
        mock_db = MagicMock()
        
        def _mock_execute(query, *args):
            mock_db.last_query = query
            mock_db.last_args = args
            return mock_cursor
            
        mock_db.execute = MagicMock(side_effect=_mock_execute)
        
        # Add commit as AsyncMock since it's awaited
        mock_db.commit = AsyncMock()
        
        @asynccontextmanager
        async def _mock_conn():
            yield mock_db
            
        mock_conn.side_effect = _mock_conn
        yield mock_cursor

@pytest.mark.unit
def test_login_page_unauthenticated(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Login" in response.text

@pytest.mark.unit
def test_login_submit_success(client, mock_db_login):
    response = client.post("/login", data={"username": "admin", "password": "password123"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "qm_session" in response.cookies

@pytest.mark.unit
def test_login_submit_invalid_password(client, mock_db_login):
    response = client.post("/login", data={"username": "admin", "password": "wrong_password"}, follow_redirects=False)
    assert response.status_code == 401
    assert "Invalid username or password" in response.text

@pytest.mark.unit
def test_login_submit_unknown_user(client, mock_db_login):
    mock_db_login.return_value = None
    response = client.post("/login", data={"username": "unknown", "password": "password123"}, follow_redirects=False)
    assert response.status_code == 401
    assert "Invalid username or password" in response.text

@pytest.mark.unit
def test_logout(client, mock_db_login):
    # Get cookie
    response = client.post("/login", data={"username": "admin", "password": "password123"}, follow_redirects=False)
    cookie = response.cookies["qm_session"]
    
    # Logout
    logout_resp = client.get("/logout", cookies={"qm_session": cookie}, follow_redirects=False)
    assert logout_resp.status_code == 303
    assert logout_resp.headers["location"] == "/login"

@pytest.mark.unit
def test_access_dashboard_unauthenticated(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

@pytest.mark.unit
def test_login_page_redirects_when_authenticated(client, mock_db_login):
    response = client.post("/login", data={"username": "admin", "password": "password123"}, follow_redirects=False)
    cookie = response.cookies["qm_session"]
    
    # Try accessing /login again
    resp = client.get("/login", cookies={"qm_session": cookie}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

@pytest.mark.unit
def test_invalid_session_cookie(client):
    # Fake/tampered cookie
    resp = client.get("/", cookies={"qm_session": "bad_cookie"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

@pytest.mark.unit
def test_login_rejects_legacy_sha256_hash(client):
    # A user row still holding a legacy SHA256 hash (pre-Argon2 migration) must be
    # rejected, not silently upgraded — the SHA256 fallback has been removed.
    with patch("api.routes.get_db_connection") as mock_conn:
        pwd_hash = hashlib.sha256(b"password123").hexdigest()

        class MockCursor:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                pass
            def __await__(self):
                async def _aw():
                    return self
                return _aw().__await__()
            async def fetchone(self):
                return (pwd_hash, "admin", 1)

        mock_cursor = MockCursor()
        mock_db = MagicMock()

        def _mock_execute(query, *args):
            mock_db.last_query = query
            mock_db.last_args = args
            return mock_cursor

        mock_db.execute = MagicMock(side_effect=_mock_execute)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def _mock_conn():
            yield mock_db

        mock_conn.side_effect = _mock_conn

        response = client.post("/login", data={"username": "admin", "password": "password123"}, follow_redirects=False)
        assert response.status_code == 401
        assert "Invalid username or password" in response.text
