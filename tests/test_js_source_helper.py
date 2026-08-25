"""Tests for the JS source helper module (Issue #388).

Provides a single shared helper that aggregates all non-vendor JavaScript files
under static/ for source-inspecting tests, decoupling them from individual file paths
during the ES module migration.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ALLOWLISTED_BASENAMES = {
    # Needs the real single-file path to read main.js mtime, does not read JS source text
    "test_static_asset_cache_busting.py",
    "test_static_asset_versioning.py",
    "test_code_quality.py",
    "test_js_source_helper.py",
}
MAIN_JS_PATH_PATTERN = re.compile(
    r"""["']static["']\s*[,/]\s*["']main\.js["']"""
)


@pytest.mark.unit
def test_read_static_js_includes_multiple_files():
    """Verify read_static_js concatenates multiple non-vendor JS files."""
    from tests.js_source import read_static_js

    content = read_static_js()
    assert "SUFFIXED_QUADLET_TYPES" in content, (
        "read_static_js() output should contain content from static/main.js"
    )
    assert "attachQuadletLint" in content, (
        "read_static_js() output should contain content from static/quadlet_lint.js"
    )


@pytest.mark.unit
def test_read_static_js_excludes_vendor():
    """Verify read_static_js excludes vendored JavaScript bundles."""
    from tests.js_source import read_static_js

    content = read_static_js()
    assert "htmx-internal-data" not in content, (
        "read_static_js() output should not include vendored JavaScript files"
    )


@pytest.mark.unit
def test_static_js_files_are_sorted_and_non_vendor():
    """Verify static_js_files returns a sorted non-empty sequence of non-vendor JS files."""
    from tests.js_source import static_js_files

    files = static_js_files()
    assert files, "static_js_files() returned an empty sequence"
    assert list(files) == sorted(files), "static_js_files() is not sorted"
    assert all(str(f).endswith(".js") for f in files), (
        "Every entry returned by static_js_files() must end with .js"
    )
    assert not any(
        "static/vendor" in str(f).replace("\\", "/") or "/vendor/" in str(f).replace("\\", "/")
        for f in files
    ), "static_js_files() must not contain paths under static/vendor/"


@pytest.mark.unit
def test_no_test_module_hardcodes_main_js_source_path():
    """Verify no test module hardcodes a path to static/main.js."""
    offending_files = []
    for root, _, files in os.walk(TESTS_DIR):
        for filename in sorted(files):
            if not filename.endswith(".py"):
                continue
            if filename in ALLOWLISTED_BASENAMES:
                continue
            filepath = os.path.join(root, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if MAIN_JS_PATH_PATTERN.search(content):
                offending_files.append(filepath)

    assert not offending_files, (
        f"Found {len(offending_files)} test files hardcoding path to static/main.js "
        f"(use tests.js_source instead):\n" + "\n".join(offending_files)
    )
