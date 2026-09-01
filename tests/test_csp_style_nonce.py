"""
Tests for issue #483: every <style> element the app emits, whether rendered by a
template or created at runtime by theme.js, must carry the per-request CSP nonce.
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
THEME_JS_PATH = STATIC_DIR / "modules" / "theme.js"


@pytest.fixture
def client():
    # Bypass login entirely so we can hit the dashboard route directly.
    with patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as test_client:
            yield test_client


def _extract_function_body(source: str, function_name: str) -> str:
    """Extract the body of a JS function by matching its name and balanced braces."""
    pattern = rf"(?:export\s+)?function\s+{function_name}\s*\([^)]*\)\s*\{{"
    match = re.search(pattern, source)
    if not match:
        return ""
    start_idx = match.end()
    depth = 1
    for i, char in enumerate(source[start_idx:], start=start_idx):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start_idx:i]
    return source[start_idx:]


@pytest.mark.unit
def test_every_template_style_tag_carries_the_nonce():
    """Walk every *.html file under templates/ recursively. For each opening
    <style tag found, assert the tag has a nonce attribute whose value is
    the Jinja expression {{ request.state.csp_nonce }}.
    """
    offenders = []
    for template_file in sorted(TEMPLATES_DIR.rglob("*.html")):
        content = template_file.read_text(encoding="utf-8")
        for match in re.finditer(r"<style\b([^>]*)>", content, re.IGNORECASE):
            tag = match.group(0)
            attrs = match.group(1)
            nonce_match = re.search(r'nonce\s*=\s*["\']\{\{\s*request\.state\.csp_nonce\s*\}\}["\']', attrs)
            if not nonce_match:
                rel_path = template_file.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel_path}: {tag}")

    assert not offenders, (
        f"Found <style> tags without nonce in templates:\n"
        + "\n".join(f"  - {entry}" for entry in offenders)
    )


@pytest.mark.unit
def test_dashboard_style_nonce_matches_the_csp_header(client):
    """GET '/' and assert the nonce attribute value on the <style id="qm-theme-overrides">
    tag in the response body matches the nonce token in the script-src CSP header.
    """
    response = client.get("/")
    assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"

    csp_header = response.headers.get("Content-Security-Policy", "")
    header_nonce_match = re.search(r"script-src\s+[^;]*'nonce-([A-Za-z0-9_-]+)'", csp_header)
    assert header_nonce_match is not None, (
        f"Content-Security-Policy header must include a 'nonce-...' token in script-src. Header: {csp_header}"
    )
    header_nonce = header_nonce_match.group(1)

    style_match = re.search(r"<style\b([^>]*\bid=[\"']qm-theme-overrides[\"'][^>]*)>", response.text, re.IGNORECASE)
    assert style_match is not None, (
        "Response body for GET '/' must contain a <style id=\"qm-theme-overrides\" ...> tag"
    )
    tag_attrs = style_match.group(1)
    nonce_match = re.search(r'\bnonce=[\'"]([^\'"]*)[\'"]', tag_attrs)
    assert nonce_match is not None, (
        f"<style id=\"qm-theme-overrides\"> opening tag must carry a nonce attribute. Found tag: {style_match.group(0)}"
    )
    style_nonce = nonce_match.group(1)

    assert style_nonce, f"<style id=\"qm-theme-overrides\"> nonce attribute must not be empty. Tag: {style_match.group(0)}"
    assert header_nonce, "CSP header nonce must not be empty"
    assert style_nonce == header_nonce, (
        f"<style id=\"qm-theme-overrides\"> nonce '{style_nonce}' does not match CSP header nonce '{header_nonce}'"
    )


@pytest.mark.unit
def test_login_style_tag_renders_a_nonce():
    """GET '/login' with a plain TestClient and assert the response body's <style>
    tag carries a non-empty nonce attribute value.
    """
    with TestClient(app) as plain_client:
        response = plain_client.get("/login")
        assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"

        style_match = re.search(r"<style\b([^>]*)>", response.text, re.IGNORECASE)
        assert style_match is not None, "Response body for GET '/login' must contain a <style> tag"
        tag_attrs = style_match.group(1)

        nonce_match = re.search(r'\bnonce=[\'"]([^\'"]*)[\'"]', tag_attrs)
        assert nonce_match is not None, (
            f"<style> tag on /login must carry a nonce attribute. Found tag: {style_match.group(0)}"
        )
        style_nonce = nonce_match.group(1)
        assert style_nonce.strip(), (
            f"<style> tag nonce on /login must not be empty. Found tag: {style_match.group(0)}"
        )


@pytest.mark.unit
def test_theme_preview_style_element_gets_the_nonce():
    """Assert that applyThemePreview in static/modules/theme.js assigns a nonce
    to the preview style element via a '.nonce =' assignment.
    """
    rel_path = THEME_JS_PATH.relative_to(REPO_ROOT).as_posix()
    assert THEME_JS_PATH.exists(), f"Expected {rel_path} to exist on disk"
    content = THEME_JS_PATH.read_text(encoding="utf-8")
    func_body = _extract_function_body(content, "applyThemePreview")
    assert func_body, f"{rel_path} must define the applyThemePreview function"
    assert re.search(r"\.nonce\s*=", func_body), (
        f"{rel_path}: applyThemePreview must assign a nonce to the created preview style element "
        f"('.nonce ='), but no such assignment was found in function body:\n{func_body}"
    )
