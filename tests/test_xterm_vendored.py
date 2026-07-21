"""
Tests for migrating the committed xterm assets onto the build-generated
static/vendor/ pipeline (Issue #201).

xterm is currently loaded by templates/dashboard.html from committed root
paths (/static/xterm.min.js, /static/xterm-addon-fit.umd.min.js,
/static/xterm.min.css), and package.json's copy-assets script copies xterm
there directly. This is the RED phase of a TDD cycle: all tests below assert
the target vendored layout (static/vendor/xterm/xterm.js,
static/vendor/xterm/xterm-addon-fit.js, static/vendor/xterm/xterm.css) that
does not exist yet, and are expected to fail until dashboard.html and
package.json are migrated.
"""
import json
import os

import pytest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
DASHBOARD_HTML_PATH = os.path.join(BASE_DIR, "templates", "dashboard.html")
PACKAGE_JSON_PATH = os.path.join(BASE_DIR, "package.json")


def _dashboard_html():
    with open(DASHBOARD_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _package_json():
    with open(PACKAGE_JSON_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.unit
def test_xterm_scripts_are_vendored():
    html = _dashboard_html()
    assert '<script src="/static/vendor/xterm/xterm.js"></script>' in html, (
        "Expected dashboard.html to load xterm from the vendored path "
        '/static/vendor/xterm/xterm.js via <script src="/static/vendor/xterm/xterm.js">. '
        "Without this, xterm is still being loaded from the committed root path."
    )
    assert '<script src="/static/vendor/xterm/xterm-addon-fit.js"></script>' in html, (
        "Expected dashboard.html to load the xterm fit addon from the vendored path "
        '/static/vendor/xterm/xterm-addon-fit.js via '
        '<script src="/static/vendor/xterm/xterm-addon-fit.js">. Without this, the fit '
        "addon is still being loaded from the committed root path."
    )


@pytest.mark.unit
def test_xterm_css_is_vendored():
    html = _dashboard_html()
    assert '<link rel="stylesheet" href="/static/vendor/xterm/xterm.css">' in html, (
        "Expected dashboard.html to load the xterm stylesheet from the vendored path "
        '/static/vendor/xterm/xterm.css via '
        '<link rel="stylesheet" href="/static/vendor/xterm/xterm.css">. Without this, the '
        "xterm CSS is still being loaded from the committed root path."
    )


@pytest.mark.unit
def test_no_committed_root_xterm_reference_in_dashboard():
    html = _dashboard_html()
    old_root_paths = [
        "/static/xterm.min.js",
        "/static/xterm-addon-fit.umd.min.js",
        "/static/xterm.min.css",
    ]
    for old_path in old_root_paths:
        assert old_path not in html, (
            f"Expected dashboard.html to no longer reference the committed root path "
            f"'{old_path}'. xterm assets must be served from static/vendor/xterm/ "
            "instead of a committed root path."
        )


@pytest.mark.unit
def test_copy_assets_vendors_xterm():
    package = _package_json()
    copy_assets = package["scripts"]["copy-assets"]
    assert "static/vendor/xterm" in copy_assets, (
        "Expected package.json's copy-assets script to copy xterm assets into "
        "static/vendor/xterm/, mirroring how Monaco and quadlet-lint are vendored. "
        f"Actual copy-assets script: {copy_assets!r}"
    )
    assert "static/xterm.min.js" not in copy_assets, (
        "Expected package.json's copy-assets script to no longer copy xterm into the "
        f"committed root target static/xterm.min.js. Actual copy-assets script: "
        f"{copy_assets!r}"
    )
