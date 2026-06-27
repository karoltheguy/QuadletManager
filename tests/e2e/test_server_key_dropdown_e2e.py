"""Playwright E2E tests for SSH key dropdown in Add Server form (issues #64, #86).

Requires the backend running on localhost:8000.
Unit tests (no browser required) live in tests/test_server_key_dropdown.py.
"""
import pytest

try:
    from playwright.sync_api import Page
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Page = typing.Any


pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT, reason="Playwright not installed"
)

BASE_URL = "http://localhost:8000"


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")
@pytest.mark.e2e
def test_ssh_key_dropdown_populated_on_settings_visit(page: Page):
    """After adding an SSH key, the dropdown in Settings > Servers must show
    that key when the user navigates to the Servers sub-section (issue #86)."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running — skipping E2E test.")

    # Navigate to Settings > SSH Keys and add a test key
    page.click("button.nav-item:has-text('Settings')")
    page.click(".settings-sidenav-item[data-section='ssh-keys']")
    page.fill("input[name='key_name']", "e2e-test-key")
    page.fill(
        "textarea[name='private_key']",
        "-----BEGIN OPENSSH PRIVATE KEY-----\nfakekey\n-----END OPENSSH PRIVATE KEY-----", # gitleaks:allow
    )
    page.click("button[type='submit']:has-text('Add Key')")
    page.wait_for_timeout(500)

    # Navigate to the Servers sub-section
    page.click(".settings-sidenav-item[data-section='servers']")
    page.wait_for_timeout(500)

    # The SSH Key dropdown must contain the key we just added
    options = page.locator("select[name='ssh_key_id'] option").all_text_contents()
    assert any("e2e-test-key" in opt for opt in options), (
        f"Expected 'e2e-test-key' in SSH key dropdown options, got: {options}"
    )
