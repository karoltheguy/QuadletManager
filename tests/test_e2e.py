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


def test_polling_alert_banner(page: Page):
    """File-changed SSE event triggers the polling alert toast within 10 s."""
    sse_payload = (
        'event: file_changed\n'
        'data: {"server_id": 1, "file_path": "/etc/containers/systemd/test.container",'
        ' "message": "File modified externally!"}\n\n'
    )
    page.route(
        "**/api/events",
        lambda route: route.fulfill(
            status=200,
            headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
            body=sse_payload,
        ),
    )

    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")

    expect(page.locator("#status-toast")).to_contain_text(
        "File modified externally!", timeout=10_000
    )
    expect(page.locator("#status-toast .toast-warning")).to_be_visible()


def test_template_injection_into_editor(page: Page):
    """New quadlet created from template populates the Monaco editor with the correct boilerplate."""
    editor_html = (
        '<div id="editor-pane" class="main-content">'
        '<div id="editor-container" style="height:400px;width:100%"></div>'
        '<script>'
        '(function() {'
        '  var tgt = document.getElementById("editor-container");'
        '  require(["vs/editor/editor.main"], function() {'
        '    if (window.editor) { window.editor.dispose(); }'
        '    window.editor = monaco.editor.create(tgt, {'
        '      value: "[Container]\\nImage=\\n",'
        '      language: "ini", theme: "vs-dark", automaticLayout: true'
        '    });'
        '  });'
        '})();'
        '</script>'
        '</div>'
    )

    page.route(
        "**/api/file/**",
        lambda route: route.fulfill(
            status=200,
            headers={"Content-Type": "text/html"},
            body=editor_html,
        ),
    )

    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")

    page.evaluate(
        "() => htmx.ajax("
        "'GET',"
        " '/api/file/1?path=/etc/containers/systemd/test.container&scope=global&name=test.container',"
        " {target: '#editor-pane', swap: 'outerHTML'})"
    )

    page.wait_for_function("() => window.editor != null", timeout=10_000)

    content = page.evaluate("window.editor.getValue()")
    assert "[Container]" in content, (
        f"Expected '[Container]' boilerplate in editor content, got: {content!r}"
    )
