"""
E2E behavioral test: the Monaco editor must follow the app light/dark theme in
'follow' mode (Issue #231; also covers the #230 live-follow regression).

Guards that the editor still follows the app theme when the app theme is
toggled. This is the behavioral coverage the earlier source-grep unit tests
could not express.
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
    not HAS_PLAYWRIGHT, reason="Playwright is not installed in this environment"
)

from tests.e2e.app_page import goto_app


@pytest.mark.e2e
def test_editor_follows_theme_toggle_in_follow_mode(page: Page):
    goto_app(page)

    # Precondition: reproduce the editor-view condition where 'monitoringChart' is
    # an undefined global. If some monitoring script defined it this session, the
    # real ReferenceError path cannot be exercised -> skip rather than false-green.
    if page.evaluate("typeof monitoringChart") != "undefined":
        pytest.skip(
            "monitoringChart is defined this session; cannot reproduce the "
            "editor-view ReferenceError condition."
        )

    # Follow mode, deterministic starting app theme = light.
    page.evaluate("localStorage.setItem('qm-editor-theme', 'follow')")
    page.evaluate("try { localStorage.removeItem('qm-theme-override'); } catch (e) {}")
    page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")

    # Inject a Monaco editor into #editor-pane, starting theme following light (vs).
    page.evaluate(
        "() => {"
        "  var pane = document.getElementById('editor-pane');"
        "  pane.innerHTML = '<div id=\"editor-container\" style=\"height:300px;width:100%\"></div>';"
        "  require(['vs/editor/editor.main'], function() {"
        "    if (window.editor) { window.editor.dispose(); }"
        "    window.editor = monaco.editor.create("
        "      document.getElementById('editor-container'),"
        "      { value: '[Container]\\nImage=\\n', language: 'ini', theme: 'vs', automaticLayout: true }"
        "    );"
        "  });"
        "}"
    )
    page.wait_for_function("() => window.editor != null", timeout=10_000)

    # Sanity: the editor starts light (vs, not vs-dark).
    page.wait_for_function(
        "() => { var e = document.querySelector('.monaco-editor');"
        " return e && e.classList.contains('vs') && !e.classList.contains('vs-dark'); }",
        timeout=10_000,
    )

    # Act: toggle the app theme via the real top-nav button (routes through toggleTheme()).
    page.click("button.theme-toggle")

    # The app theme itself must have flipped to dark.
    resolved = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert resolved == "dark", f"Expected data-theme='dark' after toggle, got {resolved!r}"

    # Assert: in follow mode the editor must now be dark too. With the bug present,
    # toggleTheme() throws in applyChartTheme() before applyEditorTheme() runs, so the
    # editor stays 'vs' and this wait times out (RED for the right reason).
    page.wait_for_function(
        "() => { var e = document.querySelector('.monaco-editor');"
        " return e && e.classList.contains('vs-dark'); }",
        timeout=5_000,
    )


@pytest.mark.e2e
def test_editor_theme_radio_persists_the_selection(page: Page):
    """Clicking an Editor Theme radio must persist it (#416).

    The other test in this file seeds 'qm-editor-theme' through localStorage, so
    nothing exercised the radio itself. Once the inline onchange became a
    delegated 'toggle-editor-theme' action, a broken dispatch would leave these
    radios inert with every unit test still green.
    """
    goto_app(page)

    page.click("button.nav-item:has-text('Settings')")
    page.click(".settings-sidenav-item[data-section='themes']")
    page.locator("#editor-theme-light").check()

    stored = page.evaluate("localStorage.getItem('qm-editor-theme')")
    assert stored == "light", (
        f"Expected the Editor Theme radio to persist 'light', got {stored!r}. "
        "The 'toggle-editor-theme' delegated action is not reaching the "
        "toggleEditorTheme handler."
    )
