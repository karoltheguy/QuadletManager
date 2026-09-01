"""
Tests for issue #484: htmx must not inject its indicator <style> element, and
components.css must carry the three rules it would otherwise have injected.
"""
import html
import json
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
STATIC_DIR = REPO_ROOT / "static"
DASHBOARD_HTML_PATH = TEMPLATES_DIR / "dashboard.html"
COMPONENTS_CSS_PATH = STATIC_DIR / "components.css"


@pytest.mark.unit
def test_dashboard_disables_htmx_indicator_styles():
    """Assert templates/dashboard.html contains a <meta name="htmx-config" ...>
    tag whose content JSON sets includeIndicatorStyles to false.
    """
    rel_path = DASHBOARD_HTML_PATH.relative_to(REPO_ROOT).as_posix()
    assert DASHBOARD_HTML_PATH.exists(), f"Expected {rel_path} to exist on disk"
    content = DASHBOARD_HTML_PATH.read_text(encoding="utf-8")

    meta_match = re.search(r"<meta\b([^>]*\bname=['\"]htmx-config['\"][^>]*)>", content, re.IGNORECASE)
    assert meta_match is not None, (
        f"{rel_path} must contain a <meta name=\"htmx-config\" ...> tag to configure htmx"
    )
    tag_attrs = meta_match.group(1)

    content_match = re.search(r'\bcontent=(["\'])(.*?)\1', tag_attrs, re.DOTALL)
    assert content_match is not None, (
        f"{rel_path}: <meta name=\"htmx-config\"> tag must have a content attribute. Tag: {meta_match.group(0)}"
    )

    raw_json = html.unescape(content_match.group(2))
    try:
        config = json.loads(raw_json)
    except Exception as err:
        pytest.fail(f"{rel_path}: Failed to parse JSON from <meta name=\"htmx-config\"> content {raw_json!r}: {err}")

    assert config.get("includeIndicatorStyles") is False, (
        f"{rel_path}: htmx-config content JSON must set 'includeIndicatorStyles' to false, got: {config}"
    )


@pytest.mark.unit
def test_components_css_defines_the_htmx_indicator_rules():
    """Assert static/components.css defines all three selectors that htmx would
    otherwise inject: .htmx-indicator, .htmx-request .htmx-indicator, and
    .htmx-request.htmx-indicator.
    """
    rel_path = COMPONENTS_CSS_PATH.relative_to(REPO_ROOT).as_posix()
    assert COMPONENTS_CSS_PATH.exists(), f"Expected {rel_path} to exist on disk"
    content = COMPONENTS_CSS_PATH.read_text(encoding="utf-8")

    # Strip CSS comments: /* ... */
    css_no_comments = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)

    # Extract all selectors preceding CSS rule blocks
    declared_selectors = set()
    for match in re.finditer(r"([^{}]+)\{", css_no_comments):
        for part in match.group(1).split(","):
            normalized = " ".join(part.split())
            if normalized:
                declared_selectors.add(normalized)

    required_selectors = [
        ".htmx-indicator",
        ".htmx-request .htmx-indicator",
        ".htmx-request.htmx-indicator",
    ]

    missing = [sel for sel in required_selectors if sel not in declared_selectors]
    assert not missing, (
        f"{rel_path} must define the following htmx indicator selector(s): {missing}. "
        f"Found selectors: {sorted(declared_selectors)}"
    )
