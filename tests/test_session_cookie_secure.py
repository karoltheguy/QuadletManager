"""Contract tests for the Secure flag on the session cookie.

The flag cannot be unconditionally on: the shipped compose file serves plain
HTTP on :8000, and a browser silently discards a Secure cookie sent over HTTP,
which would leave login appearing to succeed while never sticking. So the flag
is set when the request already arrived over HTTPS, or when the operator opts
in with the ``secure_cookies`` setting for a TLS-terminating proxy that does
not forward the scheme.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app
from core.config_loader import AppConfig
from tests.settings_mocks import mock_login_db as _mock_login_db


@pytest.fixture
def client():
    with patch("core.config_loader.global_config.dev_auto_login", False):
        with TestClient(app) as test_client:
            yield test_client


def _login_set_cookie(client, base_url="http://testserver"):
    conn_factory, _ = _mock_login_db(is_admin=True)
    with patch("api.routes.get_db_connection", side_effect=conn_factory):
        response = client.post(
            f"{base_url}/login",
            data={"username": "someone", "password": "password123"},
            follow_redirects=False,
        )
    return response.headers["set-cookie"]


@pytest.mark.unit
def test_plain_http_login_cookie_is_not_secure(client):
    """Over HTTP with the default config the cookie must stay usable."""
    with patch("core.config_loader.global_config.secure_cookies", False):
        header = _login_set_cookie(client)
    assert "secure" not in header.lower()
    assert "HttpOnly" in header


@pytest.mark.unit
def test_https_login_cookie_is_secure(client):
    """An HTTPS request gets the Secure flag with no configuration at all."""
    with patch("core.config_loader.global_config.secure_cookies", False):
        header = _login_set_cookie(client, base_url="https://testserver")
    assert "secure" in header.lower()


@pytest.mark.unit
def test_secure_cookies_setting_forces_the_flag_over_http(client):
    """The opt-in covers a proxy that terminates TLS without forwarding scheme."""
    with patch("core.config_loader.global_config.secure_cookies", True):
        header = _login_set_cookie(client)
    assert "secure" in header.lower()


@pytest.mark.unit
def test_secure_cookies_defaults_to_off(monkeypatch):
    monkeypatch.delenv("QUADLET_SECURE_COOKIES", raising=False)
    monkeypatch.setenv("QUADLET_CONFIG_PATH", "/nonexistent/config.yaml")
    assert AppConfig().secure_cookies is False


@pytest.mark.unit
def test_secure_cookies_reads_env(monkeypatch):
    monkeypatch.setenv("QUADLET_SECURE_COOKIES", "1")
    monkeypatch.setenv("QUADLET_CONFIG_PATH", "/nonexistent/config.yaml")
    assert AppConfig().secure_cookies is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [(True, True), (False, False), (1, True), (0, False), ("1", True), ("0", False)],
)
def test_secure_cookies_from_yaml(value, expected):
    config = AppConfig.__new__(AppConfig)
    config.secure_cookies = False
    config._apply_config_data({"secure_cookies": value})
    assert config.secure_cookies is expected
