import pytest

try:
    from playwright.sync_api import Page, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    Page = type('Page', (object,), {})
    def expect(x): pass

pytestmark = pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright is not installed in this environment")

# E2E test using Playwright
# To run this, the backend must be running on localhost:8000
# pytest tests/test_e2e.py

def test_editor_load(page: Page):
    """Test that the application UI loads the main elements"""
    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")
        
    expect(page.locator("h2:text('Servers')")).to_be_visible()
    
    # Switch to Editor tab to make Editor and Save buttons visible
    page.click("button.nav-item:has-text('Editor')")
    
    expect(page.locator("h2:text('Editor')")).to_be_visible()
    
    # Test Settings tab
    page.click("button.nav-item:has-text('Settings')")
    expect(page.locator("h2:text('Settings')")).to_be_visible()
