"""
Tests for static asset cache-busting on the dashboard route.

Issue: static/main.js and static/style.css are referenced from
templates/dashboard.html with no cache-busting query parameter, so a
browser can keep serving a stale cached copy after a JS/CSS fix ships,
making an already-fixed bug look "still broken" until a hard refresh.

The fix under test (not yet implemented) is expected to append
`?v=<mtime>` to those asset URLs, where `<mtime>` is the integer
modification time of the file on disk at request time - so the value
changes automatically whenever the file changes, unlike a hardcoded
app version string.
"""
import html as html_module
import os
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN_JS_PATH = os.path.join(REPO_ROOT, "static", "main.js")
STYLE_CSS_PATH = os.path.join(REPO_ROOT, "static", "style.css")


@pytest.fixture
def client():
    # Bypass login entirely so we can hit the dashboard route directly.
    with patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as test_client:
            yield test_client


@pytest.mark.unit
def test_dashboard_static_assets_carry_mtime_cache_buster(client):
    """The rendered dashboard HTML must reference main.js/style.css with
    a ?v=<mtime> query string matching the real file's mtime on disk."""
    main_js_mtime = int(os.path.getmtime(MAIN_JS_PATH))
    style_css_mtime = int(os.path.getmtime(STYLE_CSS_PATH))

    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    assert f"/static/main.js?v={main_js_mtime}" in html
    assert f"/static/style.css?v={style_css_mtime}" in html


@pytest.mark.unit
def test_dashboard_static_asset_cache_buster_changes_with_file_mtime(client):
    """The ?v= value must track the file's real mtime, not a fixed
    value such as the app version - touching the file must change it."""
    first_response = client.get("/")
    assert first_response.status_code == 200
    first_match = re.search(r"/static/main\.js\?v=(\d+)", first_response.text)
    assert first_match is not None, "expected a ?v=<mtime> query param on main.js, found none"
    first_value = first_match.group(1)

    # Bump the file's mtime forward so it is guaranteed to differ.
    current_mtime = os.path.getmtime(MAIN_JS_PATH)
    new_mtime = current_mtime + 5
    os.utime(MAIN_JS_PATH, (new_mtime, new_mtime))
    try:
        second_response = client.get("/")
        assert second_response.status_code == 200
        second_match = re.search(r"/static/main\.js\?v=(\d+)", second_response.text)
        assert second_match is not None, "expected a ?v=<mtime> query param on main.js, found none"
        second_value = second_match.group(1)

        assert first_value != second_value, (
            "the cache-busting value did not change when the file's mtime changed; "
            "it looks hardcoded rather than derived from the file's mtime"
        )
    finally:
        # Restore original mtime to avoid perturbing the working tree.
        os.utime(MAIN_JS_PATH, (current_mtime, current_mtime))


@pytest.mark.unit
def test_all_dashboard_static_assets_carry_mtime_cache_buster(client):
    """Every /static/... reference in the rendered dashboard HTML - including
    the ones inside the JSON import map - must carry a ?v=<mtime> cache
    buster matching the real file's mtime on disk."""
    response = client.get("/")
    assert response.status_code == 200
    html = html_module.unescape(response.text)

    references = re.findall(r"/static/([^\s\"'>]+)", html)
    assert references, "expected at least one /static/ reference in the dashboard HTML"

    for reference in references:
        path_part, _, query = reference.partition("?")
        expected_mtime = int(os.path.getmtime(os.path.join(REPO_ROOT, "static", path_part)))
        assert query == f"v={expected_mtime}", (
            f"/static/{path_part} is missing a matching ?v=<mtime> cache buster "
            f"(expected 'v={expected_mtime}', got {query!r})"
        )
