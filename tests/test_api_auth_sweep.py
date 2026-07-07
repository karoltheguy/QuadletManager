"""Regression sweep: every /api/* route must require an authenticated session.

Auth is applied per-handler via Depends(get_current_user_role) and friends,
so a forgotten dependency silently exposes an endpoint (see issue #164).

Two layers of protection:
1. A static sweep that walks every HTTP route under /api and asserts its
   dependency graph contains an auth-enforcing dependency. This catches any
   new route added without auth, including streaming endpoints that can't be
   safely exercised with a live request (an unauthenticated SSE stream never
   terminates under TestClient).
2. Live unauthenticated requests against the endpoints issue #164 exposed,
   asserting they redirect to login instead of executing.
"""
import pytest
from unittest.mock import patch
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from main import app
from api import routes as routes_module
from api.routes import router as web_router

# Dependencies that reject cookieless requests (all raise a 303 redirect to
# /login via _get_session when no valid session cookie is present).
AUTH_ENFORCING_DEPS = {
    routes_module.get_current_user_role,
    routes_module.get_current_user_is_admin,
    routes_module.get_current_user_id,
    routes_module.get_current_username,
}

# Status codes that prove a live request was rejected before the handler ran.
AUTH_REJECTED = {303, 401, 403}


@pytest.fixture
def client():
    with patch("core.config_loader.global_config.dev_auto_login", False):
        with TestClient(app) as test_client:
            yield test_client


def _api_routes():
    return [
        route for route in web_router.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api")
    ]


def _dependency_calls(dependant, seen=None):
    """Recursively collect the callables in a route's dependency graph."""
    if seen is None:
        seen = set()
    for dep in dependant.dependencies:
        if dep.call is not None and dep.call not in seen:
            seen.add(dep.call)
            _dependency_calls(dep, seen)
    return seen


@pytest.mark.unit
@pytest.mark.parametrize(
    "route", _api_routes(), ids=lambda r: f"{'|'.join(sorted(r.methods))}-{r.path}"
)
def test_api_route_declares_auth_dependency(route):
    calls = _dependency_calls(route.dependant)
    assert calls & AUTH_ENFORCING_DEPS, (
        f"{sorted(route.methods)} {route.path} has no auth-enforcing dependency; "
        f"add e.g. role: str = Depends(get_current_user_role)"
    )


# The endpoints issue #164 found answering unauthenticated requests.
# /api/events (SSE) is intentionally absent: while vulnerable it streams
# forever and would hang the suite; the static sweep above covers it.
EXPOSED_ENDPOINTS = [
    ("GET", "/api/overview"),
    ("GET", "/api/quadlets/1"),
    ("GET", "/api/systemctl/status/1?unit=test.container&scope=user"),
    ("GET", "/api/health/history/1"),
    ("GET", "/api/keys/options"),
]


@pytest.mark.unit
@pytest.mark.parametrize("method,url", EXPOSED_ENDPOINTS)
def test_exposed_endpoint_rejects_unauthenticated(client, method, url):
    response = client.request(method, url, follow_redirects=False)
    assert response.status_code in AUTH_REJECTED, (
        f"{method} {url} answered an unauthenticated request with "
        f"{response.status_code}; expected one of {sorted(AUTH_REJECTED)}"
    )
