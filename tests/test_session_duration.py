import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app
import api.routes as api_routes
from tests.settings_mocks import SettingsMockDB, login as _login, mock_login_db as _mock_login_db, settings_conn


@pytest.fixture
def client():
    with patch("core.config_loader.global_config.dev_auto_login", False):
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture(autouse=True)
def reset_session_duration():
    """Session duration is cached in-process; keep tests isolated from each other."""
    original = api_routes._session_duration_seconds
    yield
    api_routes._session_duration_seconds = original


@pytest.mark.unit
def test_session_duration_requires_admin(client):
    cookie = _login(client, is_admin=False)
    response = client.put(
        "/api/settings/session-duration",
        data={"session_duration_seconds": "604800"},
        cookies={"qm_session": cookie},
    )
    assert response.status_code == 403


@pytest.mark.unit
def test_session_duration_get_requires_admin(client):
    cookie = _login(client, is_admin=False)
    response = client.get(
        "/api/settings/session-duration",
        cookies={"qm_session": cookie},
    )
    assert response.status_code == 403


@pytest.mark.unit
def test_session_duration_rejects_invalid_value(client):
    cookie = _login(client, is_admin=True)
    response = client.put(
        "/api/settings/session-duration",
        data={"session_duration_seconds": "42"},
        cookies={"qm_session": cookie},
    )
    assert response.status_code == 400


@pytest.mark.unit
def test_session_duration_persists_and_applies_to_new_logins(client):
    admin_cookie = _login(client, is_admin=True)

    settings_db = SettingsMockDB()

    with patch("api.routes.get_db_connection", side_effect=lambda: settings_conn(settings_db)):
        response = client.put(
            "/api/settings/session-duration",
            data={"session_duration_seconds": "604800"},
            cookies={"qm_session": admin_cookie},
        )
    assert response.status_code == 200
    assert api_routes._session_duration_seconds == 604800

    conn_factory, _ = _mock_login_db(is_admin=True)
    with patch("api.routes.get_db_connection", side_effect=conn_factory):
        login_response = client.post(
            "/login",
            data={"username": "someone", "password": "password123"},
            follow_redirects=False,
        )
    set_cookie_header = login_response.headers["set-cookie"]
    assert "Max-Age=604800" in set_cookie_header
