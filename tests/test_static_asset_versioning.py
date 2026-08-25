"""
Tests for static asset versioning and multi-file lint targets (issue #389).

BACKGROUND:
static/main.js is being split into multiple ES modules. Static asset versioning
must move from hardcoded template context keys to a dynamic Jinja2 global
`asset_url(filename)` that appends `?v=<mtime>` for any static file on disk.
Additionally, code quality linters (ESLint) must target all non-vendor static
JS files dynamically rather than hardcoding static/main.js.
"""
import os
import pathlib
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN_JS_PATH = os.path.join(REPO_ROOT, "static", "main.js")
QUADLET_LINT_JS_PATH = os.path.join(REPO_ROOT, "static", "quadlet_lint.js")


@pytest.fixture
def client():
    # Bypass login entirely so we can hit the dashboard route directly.
    with patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as test_client:
            yield test_client


@pytest.mark.unit
def test_asset_url_is_registered_as_a_jinja_global():
    """Verify that asset_url is registered as a global function in Jinja2 templates."""
    from api.routes import templates

    assert "asset_url" in templates.env.globals


@pytest.mark.unit
def test_asset_url_appends_mtime_for_any_static_file():
    """Verify asset_url returns /static/<name>?v=<mtime> for any static file."""
    from api.routes import templates

    asset_url = templates.env.globals["asset_url"]
    main_js_mtime = int(os.path.getmtime(MAIN_JS_PATH))
    quadlet_lint_mtime = int(os.path.getmtime(QUADLET_LINT_JS_PATH))

    assert asset_url("main.js") == f"/static/main.js?v={main_js_mtime}"
    assert asset_url("quadlet_lint.js") == f"/static/quadlet_lint.js?v={quadlet_lint_mtime}"


@pytest.mark.unit
def test_dashboard_versions_quadlet_lint_module(client):
    """The rendered dashboard HTML must reference quadlet_lint.js with
    a ?v=<mtime> query string matching the real file's mtime on disk."""
    quadlet_lint_mtime = int(os.path.getmtime(QUADLET_LINT_JS_PATH))

    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    assert f"/static/quadlet_lint.js?v={quadlet_lint_mtime}" in html


@pytest.mark.unit
def test_dashboard_quadlet_lint_urls_are_identical(client):
    """All references to quadlet_lint.js in the rendered dashboard HTML must use
    identical URLs including the cache-busting query parameter.

    Two different URLs make the browser load two separate module instances,
    which registers the Monaco providers twice.
    """
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    matches = re.findall(r"(/static/quadlet_lint\.js\?[^\s\"'>]+)", html)
    assert len(matches) >= 2, f"expected at least 2 versioned quadlet_lint.js URLs, found {len(matches)}"
    assert len(set(matches)) == 1, f"expected all captured quadlet_lint.js URLs to be identical, got {matches}"


@pytest.mark.unit
def test_eslint_targets_cover_every_non_vendor_static_js():
    """Verify that _eslint_targets() dynamically discovers all non-vendor static JS files."""
    from tests.js_source import static_js_files
    from tests.test_code_quality import _eslint_targets

    expected_targets = sorted(
        pathlib.Path(p).relative_to(REPO_ROOT).as_posix()
        for p in static_js_files()
    )
    assert sorted(_eslint_targets()) == expected_targets
