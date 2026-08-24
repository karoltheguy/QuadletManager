"""Pins the AuthRedirect exception contract for unauthenticated requests."""
import os
import sys
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api import routes as routes_module
from main import app


@pytest.mark.unit
async def test_cookieless_session_raises_auth_redirect_to_login():
    """Unauthenticated session lookup raises AuthRedirect pointing to LOGIN_PATH."""
    cookieless = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/keys",
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "query_string": b"",
        "headers": [],
    })

    with patch("core.config_loader.global_config.dev_auto_login", False):
        with pytest.raises(routes_module.AuthRedirect) as excinfo:
            await routes_module._get_session(cookieless)

    assert excinfo.value.location == routes_module.LOGIN_PATH, (
        f"Expected location {routes_module.LOGIN_PATH}, got {excinfo.value.location}"
    )
    assert excinfo.value.status_code == 303, (
        f"Expected status code 303, got {excinfo.value.status_code}"
    )
    assert 303 in routes_module.AUTH_REDIRECT_RESPONSES, (
        "Status code 303 must be registered in AUTH_REDIRECT_RESPONSES"
    )


@pytest.mark.unit
def test_auth_redirect_is_not_an_http_exception():
    """AuthRedirect must not subclass HTTPException to stop reusing the error type."""
    assert not issubclass(routes_module.AuthRedirect, HTTPException), (
        "AuthRedirect should not be a subclass of HTTPException"
    )


@pytest.mark.unit
def test_auth_redirect_response_has_no_body():
    """Cookieless request to auth-protected endpoint returns 303 redirect with empty body."""
    with patch("core.config_loader.global_config.dev_auto_login", False):
        with TestClient(app) as client:
            response = client.get("/api/keys", follow_redirects=False)

    assert response.status_code == 303, f"Expected 303, got {response.status_code}"
    assert response.headers["location"] == "/login", (
        f"Expected location '/login', got {response.headers.get('location')}"
    )
    assert response.content == b"", f"Expected empty body, got {response.content!r}"
    assert "content-type" not in response.headers, (
        f"Expected no content-type header, got {response.headers.get('content-type')}"
    )
