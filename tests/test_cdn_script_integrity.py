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

TESTS_DIR = os.path.dirname(__file__)
HTML_PATH = os.path.join(TESTS_DIR, "..", "templates", "dashboard.html")
MAIN_JS_PATH = os.path.join(TESTS_DIR, "..", "static", "main.js")
TEMPLATES_DIR = os.path.join(TESTS_DIR, "..", "templates")
STATIC_DIR = os.path.join(TESTS_DIR, "..", "static")

CDNJS_SUBSTRING = "cdnjs.cloudflare.com"
VENDORED_MONACO_PREFIX = "/static/vendor/monaco/"

MONACO_LOADER_SRC_RE = re.compile(r'src="/static/vendor/monaco/[^"]*loader[^"]*\.js"')


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
def test_main_js_require_config_uses_vendored_vs_path():
    main_js = _read_text(MAIN_JS_PATH)
    assert VENDORED_MONACO_PREFIX + "vs" in main_js, (
        "Expected static/main.js's require.config({ paths: { 'vs': ... } }) to "
        f"point at the same-origin vendored path '{VENDORED_MONACO_PREFIX}vs' "
        "instead of the cdnjs CDN URL."
    )
