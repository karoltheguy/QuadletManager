import logging

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
def reset_log_level():
    """Log level is cached in-process; keep tests isolated from each other."""
    original = api_routes._log_level
    yield
    api_routes._log_level = original


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_log_level_ignores_invalid_stored_value():
    settings_db = SettingsMockDB()
    settings_db.store["log_level"] = "VERBOSE"


    logger = logging.getLogger("quadlet-manager")
    original_level = logger.level

    with patch("api.routes.get_db_connection", side_effect=lambda: settings_conn(settings_db)):
        await api_routes._load_log_level_from_db()

    assert logger.level == original_level


@pytest.mark.unit
def test_log_level_persists_and_applies_live(client):
    admin_cookie = _login(client, is_admin=True)

    settings_db = SettingsMockDB()

    with patch("api.routes.get_db_connection", side_effect=lambda: settings_conn(settings_db)):
        response = client.put(
            "/api/settings/log-level",
            data={"log_level": "DEBUG"},
            cookies={"qm_session": admin_cookie},
        )
    assert response.status_code == 200
    assert settings_db.store.get("log_level") == "DEBUG"
    assert logging.getLogger("quadlet-manager").level == logging.DEBUG
