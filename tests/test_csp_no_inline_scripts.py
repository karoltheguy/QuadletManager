"""
Tests for issue #472: removing 'unsafe-inline' from script-src CSP by eliminating
inline scripts and loading theme boot scripts externally.
"""
import pathlib
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
STATIC_DIR = REPO_ROOT / "static"
DASHBOARD_HTML_PATH = TEMPLATES_DIR / "dashboard.html"
LOGIN_HTML_PATH = TEMPLATES_DIR / "login.html"
CHANGE_PASSWORD_HTML_PATH = TEMPLATES_DIR / "change_password.html"
THEME_BOOT_JS_PATH = STATIC_DIR / "theme_boot.js"
AUTH_THEME_BOOT_JS_PATH = STATIC_DIR / "auth_theme_boot.js"


@pytest.fixture
def client():
    # Bypass login entirely so we can hit the dashboard route directly.
    with patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as test_client:
            yield test_client


@pytest.mark.unit
def test_no_template_has_an_inline_script():
    """Walk every *.html template and verify no inline <script> tags exist,
    excluding <script type="importmap">.
    """
    inline_scripts = []
    for template_file in sorted(TEMPLATES_DIR.rglob("*.html")):
        content = template_file.read_text(encoding="utf-8")
        for match in re.finditer(r"<script\b([^>]*)>", content, re.IGNORECASE):
            tag = match.group(0)
            attrs = match.group(1)
            has_src = bool(re.search(r"\bsrc\s*=", attrs, re.IGNORECASE))
            is_importmap = bool(re.search(r'\btype\s*=\s*["\']importmap["\']', attrs, re.IGNORECASE))
            if not has_src and not is_importmap:
                rel_path = template_file.relative_to(REPO_ROOT).as_posix()
                inline_scripts.append(f"{rel_path}: {tag}")

    assert not inline_scripts, (
        f"Found inline <script> tags without src in templates:\n"
        + "\n".join(f"  - {entry}" for entry in inline_scripts)
    )


@pytest.mark.unit
def test_dashboard_loads_theme_boot_script():
    """Assert templates/dashboard.html loads theme_boot.js as a classic script (not type="module")."""
    content = DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
    script_tags = re.findall(r"<script\b[^>]*>", content, re.IGNORECASE)
    matching_tags = [
        tag
        for tag in script_tags
        if re.search(r"src\s*=\s*[\"']\{\{\s*asset_url\(['\"]theme_boot\.js['\"]\)\s*\}\}[\"']", tag)
    ]
    assert matching_tags, (
        "templates/dashboard.html must contain a <script> tag with src rendered by asset_url('theme_boot.js')"
    )
    for tag in matching_tags:
        assert not re.search(r'\btype\s*=\s*["\']module["\']', tag, re.IGNORECASE), (
            f"templates/dashboard.html theme_boot.js <script> tag must not have type=\"module\": {tag}"
        )


@pytest.mark.unit
def test_auth_pages_load_auth_theme_boot_script():
    """Assert templates/login.html and templates/change_password.html load auth_theme_boot.js as a classic script."""
    for template_path in [LOGIN_HTML_PATH, CHANGE_PASSWORD_HTML_PATH]:
        rel_path = template_path.relative_to(REPO_ROOT).as_posix()
        content = template_path.read_text(encoding="utf-8")
        script_tags = re.findall(r"<script\b[^>]*>", content, re.IGNORECASE)
        matching_tags = [
            tag
            for tag in script_tags
            if re.search(r"src\s*=\s*[\"']\{\{\s*asset_url\(['\"]auth_theme_boot\.js['\"]\)\s*\}\}[\"']", tag)
        ]
        assert matching_tags, (
            f"{rel_path} must contain a <script> tag with src rendered by asset_url('auth_theme_boot.js')"
        )
        for tag in matching_tags:
            assert not re.search(r'\btype\s*=\s*["\']module["\']', tag, re.IGNORECASE), (
                f"{rel_path} auth_theme_boot.js <script> tag must not have type=\"module\": {tag}"
            )


@pytest.mark.unit
def test_theme_boot_files_exist():
    """Assert both static/theme_boot.js and static/auth_theme_boot.js exist on disk and are non-empty."""
    for script_path in [THEME_BOOT_JS_PATH, AUTH_THEME_BOOT_JS_PATH]:
        rel_path = script_path.relative_to(REPO_ROOT).as_posix()
        assert script_path.exists(), f"Expected static asset {rel_path} to exist on disk"
        assert script_path.stat().st_size > 0, f"Expected static asset {rel_path} to be non-empty"


@pytest.mark.unit
def test_dashboard_html_element_carries_theme_pref(client):
    """Assert GET '/' returns status 200 and the <html> tag carries a non-empty data-theme-pref attribute."""
    response = client.get("/")
    assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"
    html = response.text

    html_tag_match = re.search(r"<html\b([^>]*)>", html, re.IGNORECASE)
    assert html_tag_match is not None, "Response HTML must contain an <html> tag"

    html_attrs = html_tag_match.group(1)
    pref_match = re.search(r'\bdata-theme-pref=[\'"]([^\'"]+)[\'"]', html_attrs)
    assert pref_match is not None and pref_match.group(1).strip() != "", (
        f"The <html> tag must carry a non-empty data-theme-pref attribute, found <html> tag: {html_tag_match.group(0)}"
    )
