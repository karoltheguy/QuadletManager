"""
Tests for subresource integrity (SRI) on CDN-loaded scripts (Issue #126).
CodeQL alert js/functionality-from-untrusted-source flagged the monaco-editor
loader script for having no integrity check.
"""
import os
import re

import pytest

HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")

MONACO_SRC = "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.min.js"


def _html():
    with open(HTML_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.mark.unit
def test_monaco_loader_script_tag_present():
    assert MONACO_SRC in _html()


@pytest.mark.unit
def test_monaco_loader_has_integrity_attribute():
    html = _html()
    match = re.search(
        r'<script[^>]*src="' + re.escape(MONACO_SRC) + r'"[^>]*>',
        html,
    )
    assert match, "Expected the monaco-editor loader <script> tag in dashboard.html"
    tag = match.group(0)
    assert 'integrity="sha384-' in tag, (
        "Expected an integrity=\"sha384-...\" attribute on the monaco-editor loader "
        "script tag to satisfy CodeQL js/functionality-from-untrusted-source (#126)"
    )
    assert 'crossorigin="anonymous"' in tag, (
        "Expected crossorigin=\"anonymous\" alongside the integrity attribute"
    )
