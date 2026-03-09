import pytest
from playwright.sync_api import Page, expect

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
    expect(page.locator("h2:text('Editor')")).to_be_visible()
    
    # Check if 'Save Quadlet' button exists
    expect(page.locator("button:text('Save Quadlet')")).to_be_visible()
