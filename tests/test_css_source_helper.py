"""Tests for the CSS source helper module.

Provides a single shared helper that aggregates all non-vendor CSS files
under static/ for source-inspecting tests, decoupling them from individual file paths.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ALLOWLISTED_BASENAMES = {
    "test_static_asset_cache_busting.py",  # reads style.css mtime, not source text
    "test_css_source_helper.py",  # this file defines the pattern itself
}
STYLE_CSS_PATH_PATTERN = re.compile(
    r"""["']static["']\s*[,/]\s*["']style\.css["']"""
)


@pytest.mark.unit
def test_read_static_css_includes_style_css():
    """Verify read_static_css returns non-vendor CSS content from static/style.css."""
    from tests.css_source import read_static_css

    content = read_static_css()
    assert "--brand-primary" in content, (
        "read_static_css() output should contain content from static/style.css"
    )


@pytest.mark.unit
def test_read_static_css_excludes_vendor():
    """Verify read_static_css excludes vendored CSS files."""
    from tests.css_source import read_static_css

    content = read_static_css()
    assert "xterm-helper-textarea" not in content, (
        "read_static_css() output should not include vendored CSS files"
    )


@pytest.mark.unit
def test_static_css_files_are_sorted_and_non_vendor():
    """Verify static_css_files returns a sorted non-empty sequence of non-vendor CSS files."""
    from tests.css_source import static_css_files

    files = static_css_files()
    assert files, "static_css_files() returned an empty sequence"
    assert list(files) == sorted(files), "static_css_files() is not sorted"
    assert all(str(f).endswith(".css") for f in files), (
        "Every entry returned by static_css_files() must end with .css"
    )
    assert not any(
        "static/vendor" in str(f).replace("\\", "/") or "/vendor/" in str(f).replace("\\", "/")
        for f in files
    ), "static_css_files() must not contain paths under static/vendor/"


@pytest.mark.unit
def test_no_test_module_hardcodes_style_css_source_path():
    """Verify no test module hardcodes a path to static/style.css."""
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
            if STYLE_CSS_PATH_PATTERN.search(content):
                offending_files.append(filepath)

    assert not offending_files, (
        f"Found {len(offending_files)} test files hardcoding path to static/style.css "
        f"(use tests.css_source instead):\n" + "\n".join(offending_files)
    )
