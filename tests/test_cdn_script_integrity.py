"""
Tests for the Monaco Editor loading contract (Issues #126, #218).

Issue #126: CodeQL alert js/functionality-from-untrusted-source flagged the
monaco-editor loader script for being loaded from a third-party CDN
(cdnjs.cloudflare.com) with no integrity check.

Issue #218 resolves #126 at its source rather than sidestepping it: instead of
adding subresource integrity (SRI) attributes to a cross-origin script tag,
Monaco Editor is now vendored into `static/vendor/monaco/` and served
same-origin. A same-origin asset served by this application is trusted by
construction and does not need an integrity/crossorigin attribute -- there is
no "functionality from untrusted source" to flag. These tests assert that the
loader is self-hosted and that no reference to cdnjs.cloudflare.com remains
anywhere in the served templates/static assets.
"""
import os
import re

import pytest

from tests.js_source import read_static_js

TESTS_DIR = os.path.dirname(__file__)
HTML_PATH = os.path.join(TESTS_DIR, "..", "templates", "dashboard.html")
TEMPLATES_DIR = os.path.join(TESTS_DIR, "..", "templates")
STATIC_DIR = os.path.join(TESTS_DIR, "..", "static")

CDNJS_SUBSTRING = "cdnjs.cloudflare.com"
VENDORED_MONACO_PREFIX = "/static/vendor/monaco/"

MONACO_LOADER_SRC_RE = re.compile(
    r'src="(?:'
    r'/static/vendor/monaco/[^"]*loader[^"]*\.js'
    r'|'
    r"\{\{\s*asset_url\(\s*['\"]vendor/monaco/[^'\"]*loader[^'\"]*\.js['\"]\s*\)\s*\}\}"
    r')"'
)

# A <script> whose src points at an absolute URL, i.e. a host we do not control.
CROSS_ORIGIN_SCRIPT_RE = re.compile(r'<script[^>]*\ssrc="((?:https?:)?//[^"]+)"')


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _iter_scan_files():
    """Yield paths of every file under templates/ and static/, skipping the
    build-generated (and gitignored) static/vendor/ directory."""
    for base_dir in (TEMPLATES_DIR, STATIC_DIR):
        for root, dirs, files in os.walk(base_dir):
            # Skip the vendored assets directory entirely -- it's build
            # generated and gitignored, not something we author or review.
            if os.path.abspath(root) == os.path.abspath(STATIC_DIR):
                dirs[:] = [d for d in dirs if d != "vendor"]
            for name in files:
                yield os.path.join(root, name)


@pytest.mark.unit
def test_monaco_loader_is_self_hosted():
    html = _read_text(HTML_PATH)
    match = MONACO_LOADER_SRC_RE.search(html)
    assert match, (
        "Expected a <script> tag in dashboard.html with a src attribute matching "
        "/static/vendor/monaco/*loader*.js (self-hosted monaco loader), got none. "
        "Monaco should be vendored and served same-origin per issue #218."
    )


@pytest.mark.unit
def test_no_cdnjs_monaco_reference_anywhere():
    offenders = []
    for path in _iter_scan_files():
        try:
            content = _read_text(path)
        except (UnicodeDecodeError, OSError):
            # Skip binary files or files we can't decode as text.
            continue
        if CDNJS_SUBSTRING in content:
            offenders.append(path)
    assert not offenders, (
        "Found references to cdnjs.cloudflare.com in the following files, but "
        "Monaco must be fully self-hosted from static/vendor/monaco/ per "
        f"issue #218: {offenders}"
    )


@pytest.mark.unit
def test_no_template_loads_a_script_from_a_third_party_host():
    """Every <script src> must be served same-origin.

    htmx and chart.js used to be hot-linked from unpkg and jsdelivr, which
    meant the dashboard executed third-party bytes in an authenticated
    session and could not load at all without internet access. They are now
    vendored into static/vendor/ by copy-assets, the same way Monaco was in
    issue #218. This test keeps a CDN URL from creeping back in.

    Scoped to scripts, which are the code-execution boundary. The Google
    Fonts stylesheets on login.html and change_password.html are a separate
    (privacy and offline-availability) concern, not covered here.
    """
    offenders = []
    for path in _iter_scan_files():
        if not path.endswith((".html", ".htm")):
            continue
        try:
            content = _read_text(path)
        except (UnicodeDecodeError, OSError):
            continue
        for src in CROSS_ORIGIN_SCRIPT_RE.findall(content):
            offenders.append((os.path.basename(path), src))
    assert not offenders, (
        "These templates load a script from a host we do not control. Vendor "
        "it via package.json + the copy-assets script and serve it from "
        f"/static/vendor/ instead: {offenders}"
    )


@pytest.mark.unit
def test_main_js_require_config_uses_vendored_vs_path():
    main_js = read_static_js()
    assert VENDORED_MONACO_PREFIX + "vs" in main_js, (
        "Expected static/main.js's require.config({ paths: { 'vs': ... } }) to "
        f"point at the same-origin vendored path '{VENDORED_MONACO_PREFIX}vs' "
        "instead of the cdnjs CDN URL."
    )
