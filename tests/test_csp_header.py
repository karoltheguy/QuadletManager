"""
Tests for issue #472: Content-Security-Policy (CSP) response headers,
per-request script nonces, and importmap nonce propagation.
"""
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app


def parse_csp_header(csp_header: str) -> dict[str, list[str]]:
    """Parse a Content-Security-Policy header string into a dict of {directive_name: [tokens]}."""
    directives = {}
    if not csp_header:
        return directives
    for part in csp_header.split(";"):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if tokens:
            directive_name = tokens[0]
            directive_values = tokens[1:]
            directives[directive_name] = directive_values
    return directives


@pytest.fixture
def client():
    # Bypass login entirely so we can hit the dashboard route directly.
    with patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as test_client:
            yield test_client


@pytest.mark.unit
def test_dashboard_response_sets_csp_header(client):
    """GET '/' returns 200 and the response has a non-empty Content-Security-Policy header."""
    response = client.get("/")
    assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"
    csp = response.headers.get("Content-Security-Policy")
    assert csp is not None and len(csp.strip()) > 0, (
        "GET '/' response must include a non-empty 'Content-Security-Policy' header"
    )


@pytest.mark.unit
def test_script_src_allows_self_and_a_nonce(client):
    """Parse header from GET '/'. script-src directive contains ''self'' and exactly one nonce token."""
    response = client.get("/")
    assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"
    csp_header = response.headers.get("Content-Security-Policy", "")
    parsed = parse_csp_header(csp_header)
    assert "script-src" in parsed, (
        "Content-Security-Policy header must include a 'script-src' directive"
    )
    script_src = parsed["script-src"]
    assert "'self'" in script_src, (
        "script-src directive must contain ''self'' to allow first-party scripts"
    )
    nonce_pattern = re.compile(r"^'nonce-[A-Za-z0-9_-]+'$")
    nonce_tokens = [t for t in script_src if nonce_pattern.match(t)]
    assert len(nonce_tokens) == 1, (
        f"script-src directive must contain exactly one token matching ^'nonce-[A-Za-z0-9_-]+'$, found: {nonce_tokens}"
    )


@pytest.mark.unit
def test_script_src_forbids_unsafe_inline_and_unsafe_eval(client):
    """Assert script-src contains neither ''unsafe-inline'' nor ''unsafe-eval''."""
    response = client.get("/")
    assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"
    csp_header = response.headers.get("Content-Security-Policy", "")
    parsed = parse_csp_header(csp_header)
    assert "script-src" in parsed, (
        "Content-Security-Policy header must include a 'script-src' directive without 'unsafe-inline' "
        "(issue #472: an inline script would otherwise be allowed)"
    )
    script_src = parsed["script-src"]
    assert "'unsafe-inline'" not in script_src, (
        "script-src must not contain ''unsafe-inline'' (issue #472: an inline script would otherwise be allowed)"
    )
    assert "'unsafe-eval'" not in script_src, (
        "script-src must not contain ''unsafe-eval'' (issue #472: an inline script would otherwise be allowed)"
    )


@pytest.mark.unit
def test_importmap_tag_carries_the_header_nonce(client):
    """Assert the importmap tag carries a nonce attribute matching the script-src header nonce."""
    response = client.get("/")
    assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"
    csp_header = response.headers.get("Content-Security-Policy", "")
    parsed = parse_csp_header(csp_header)
    assert "script-src" in parsed, (
        "Content-Security-Policy header must include a 'script-src' directive with a per-request nonce"
    )

    nonce_pattern = re.compile(r"^'nonce-([A-Za-z0-9_-]+)'$")
    nonces = [nonce_pattern.match(t).group(1) for t in parsed["script-src"] if nonce_pattern.match(t)]
    assert len(nonces) == 1, (
        f"Expected exactly one 'nonce-...' token in script-src, found: {parsed['script-src']}"
    )
    header_nonce = nonces[0]

    match = re.search(r"<script\b([^>]*\btype=['\"]importmap['\"][^>]*)>", response.text, re.IGNORECASE)
    assert match is not None, "Response body must contain a <script type=\"importmap\"> tag"
    tag_attrs = match.group(1)

    nonce_match = re.search(r'\bnonce=[\'"]([^\'"]+)[\'"]', tag_attrs)
    assert nonce_match is not None, (
        f"<script type=\"importmap\"> opening tag must carry a nonce attribute. Tag: {match.group(0)}. "
        "Without this the import map is blocked and every @qm/... module import in the app fails."
    )
    assert nonce_match.group(1) == header_nonce, (
        f"<script type=\"importmap\"> nonce '{nonce_match.group(1)}' does not match CSP header nonce '{header_nonce}'. "
        "Without this the import map is blocked and every @qm/... module import in the app fails."
    )


@pytest.mark.unit
def test_nonce_differs_between_requests(client):
    """Issue two GET '/' requests and assert nonces in headers differ."""
    r1 = client.get("/")
    r2 = client.get("/")
    assert r1.status_code == 200, f"Expected status code 200 for request 1, got {r1.status_code}"
    assert r2.status_code == 200, f"Expected status code 200 for request 2, got {r2.status_code}"

    csp1 = parse_csp_header(r1.headers.get("Content-Security-Policy", ""))
    csp2 = parse_csp_header(r2.headers.get("Content-Security-Policy", ""))

    assert "script-src" in csp1, (
        "First request Content-Security-Policy header must include a 'script-src' directive with a nonce"
    )
    assert "script-src" in csp2, (
        "Second request Content-Security-Policy header must include a 'script-src' directive with a nonce"
    )

    nonce_pattern = re.compile(r"^'nonce-([A-Za-z0-9_-]+)'$")
    nonces1 = [nonce_pattern.match(t).group(1) for t in csp1["script-src"] if nonce_pattern.match(t)]
    nonces2 = [nonce_pattern.match(t).group(1) for t in csp2["script-src"] if nonce_pattern.match(t)]

    assert len(nonces1) == 1, (
        f"First request script-src must contain exactly one nonce token, found: {csp1['script-src']}"
    )
    assert len(nonces2) == 1, (
        f"Second request script-src must contain exactly one nonce token, found: {csp2['script-src']}"
    )

    assert nonces1[0] != nonces2[0], (
        f"Nonce must differ between requests (got '{nonces1[0]}' for both). A reused nonce is equivalent to 'unsafe-inline'."
    )


@pytest.mark.unit
def test_login_page_sets_csp_header():
    """GET '/login' with plain TestClient returns 200 and carries CSP header with script-src containing ''self''."""
    with TestClient(app) as plain_client:
        response = plain_client.get("/login")
        assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"
        csp_header = response.headers.get("Content-Security-Policy", "")
        parsed = parse_csp_header(csp_header)
        assert "script-src" in parsed, (
            "GET '/login' response must include a Content-Security-Policy header with 'script-src'. "
            "The header must not be limited to the dashboard route."
        )
        assert "'self'" in parsed["script-src"], (
            "GET '/login' CSP script-src directive must contain ''self''. "
            "The header must not be limited to the dashboard route."
        )


@pytest.mark.unit
def test_csp_restricts_objects_framing_and_base_uri(client):
    """Assert object-src == [\"'none'\"], frame-ancestors == [\"'none'\"], and base-uri == [\"'self'\"]."""
    response = client.get("/")
    assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"
    csp_header = response.headers.get("Content-Security-Policy", "")
    parsed = parse_csp_header(csp_header)
    assert parsed.get("object-src") == ["'none'"], (
        f"Expected object-src to be [\"'none'\"], got {parsed.get('object-src')}"
    )
    assert parsed.get("frame-ancestors") == ["'none'"], (
        f"Expected frame-ancestors to be [\"'none'\"], got {parsed.get('frame-ancestors')}"
    )
    assert parsed.get("base-uri") == ["'self'"], (
        f"Expected base-uri to be [\"'self'\"], got {parsed.get('base-uri')}"
    )
