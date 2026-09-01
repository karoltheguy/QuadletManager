"""
E2E tests for theme customization (Issue #78).
Acceptance gate: test_no_fouc_on_reload_with_active_custom_theme
"""
import pytest

try:
    from playwright.sync_api import Page, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Page = typing.Any

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="Playwright is not installed in this environment"
)

from tests.app_url import BASE_URL
_CANARY_DARK_BG = "#0a1628"
_DEFAULT_DARK_BG = "#1c1f24"


def _goto_themes(page: Page):
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip(f"Backend is not running on {BASE_URL} — skipping E2E tests.")
    page.click("button.nav-item:has-text('Settings')")
    expect(page.locator("#settings-pane")).to_be_visible()
    page.click(".settings-sidenav-item[data-section='themes']")
    expect(page.locator(".theme-list")).to_be_visible(timeout=5000)


@pytest.mark.e2e
def test_themes_tab_appears_in_settings_sidenav(page: Page):
    """Settings sidenav must show a Themes item that reveals the htmx-loaded theme editor."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip(f"Backend is not running on {BASE_URL} — skipping E2E tests.")

    page.click("button.nav-item:has-text('Settings')")
    expect(page.locator("#settings-pane")).to_be_visible()

    themes_nav = page.locator(".settings-sidenav-item[data-section='themes']")
    expect(themes_nav).to_be_visible()

    themes_nav.click()
    expect(page.locator(".settings-group[data-group='themes']")).to_be_visible()
    expect(page.locator(".theme-list")).to_be_visible(timeout=5000)


@pytest.mark.e2e
def test_color_picker_change_applies_css_var(page: Page):
    """Saving a dark bg_base must persist it so --bg-base reflects the value after reload."""
    _goto_themes(page)

    page.click(".color-editor .seg-btn:has-text('Dark mode')")
    dark_form = page.locator("form.color-editor-form[data-mode='dark']")
    hex_input = dark_form.locator("#dark-1")  # dark-1 = bg_base (first in fixed allowlist)
    hex_input.fill(_CANARY_DARK_BG)
    with page.expect_response("**/api/settings/themes/**"):
        dark_form.locator("button:has-text('Save')").click()
    expect(page.locator(".theme-list")).to_be_visible(timeout=5000)

    # Reload so the server-rendered qm-theme-overrides block reflects the saved color.
    page.reload()
    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")

    bg_base = page.evaluate(
        "window.getComputedStyle(document.documentElement)"
        ".getPropertyValue('--bg-base').trim()"
    )
    try:
        assert bg_base == _CANARY_DARK_BG, (
            f"Expected --bg-base={_CANARY_DARK_BG!r} after dark mode save+reload, got {bg_base!r}"
        )
    finally:
        _goto_themes(page)
        page.click(".color-editor .seg-btn:has-text('Dark mode')")
        df = page.locator("form.color-editor-form[data-mode='dark']")
        df.locator("#dark-1").fill(_DEFAULT_DARK_BG)
        with page.expect_response("**/api/settings/themes/**"):
            df.locator("button:has-text('Save')").click()
        expect(page.locator(".theme-list")).to_be_visible(timeout=5000)


@pytest.mark.e2e
def test_neumorphic_shadows_preserved_after_custom_theme(page: Page):
    """All 8 allowlist color overrides must not bleed into the composite shadow on .top-nav."""
    _goto_themes(page)
    page.click(".color-editor .seg-btn:has-text('Dark mode')")
    dark_form = page.locator("form.color-editor-form[data-mode='dark']")

    # Fill every allowlist slot with a valid but non-default color.
    # Order matches the fixed allowlist: bg_base, bg_surface, text_primary, text_muted,
    # brand_primary, success, danger, border_color.
    test_colors = [
        ("#dark-1", "#0a1020"), ("#dark-2", "#0c1428"), ("#dark-3", "#dce8f0"),
        ("#dark-4", "#8090a0"), ("#dark-5", "#13a090"), ("#dark-6", "#0f9e70"),
        ("#dark-7", "#de3333"), ("#dark-8", "#1a2030"),
    ]
    for input_id, color in test_colors:
        dark_form.locator(input_id).fill(color)

    with page.expect_response("**/api/settings/themes/**"):
        dark_form.locator("button:has-text('Save')").click()
    expect(page.locator(".theme-list")).to_be_visible(timeout=5000)

    page.reload()
    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")

    box_shadow = page.evaluate(
        "window.getComputedStyle(document.querySelector('.top-nav')).boxShadow"
    )
    try:
        assert box_shadow != "none", (
            "Expected composite neumorphic shadow on .top-nav, got 'none'"
        )
        assert box_shadow.count(",") >= 1, (
            f"Expected 2-layer shadow on .top-nav (shadow vars not overridden), "
            f"got: {box_shadow!r}"
        )
    finally:
        _goto_themes(page)
        page.click(".color-editor .seg-btn:has-text('Dark mode')")
        page.once("dialog", lambda d: d.accept())
        with page.expect_response("**/api/settings/themes/**"):
            page.locator(
                "form.color-editor-form[data-mode='dark'] button:has-text('Reset')"
            ).click()
        expect(page.locator(".theme-list")).to_be_visible(timeout=5000)


@pytest.mark.e2e
def test_no_fouc_on_reload_with_active_custom_theme(page: Page):
    """
    ACCEPTANCE GATE: data-theme must be set before DOMContentLoaded and the
    qm-theme-overrides style block must carry the custom color in the initial HTML.
    If this test fails, the FOUC prevention strategy in #75 is broken.
    """
    _goto_themes(page)
    page.click(".color-editor .seg-btn:has-text('Dark mode')")
    dark_form = page.locator("form.color-editor-form[data-mode='dark']")
    dark_form.locator("#dark-1").fill(_CANARY_DARK_BG)
    with page.expect_response("**/api/settings/themes/**"):
        dark_form.locator("button:has-text('Save')").click()
    expect(page.locator(".theme-list")).to_be_visible(timeout=5000)

    # Init script runs before any page script; sets up a DOMContentLoaded capture.
    # The inline FOUC script in <head> runs synchronously during parsing, so
    # data-theme is already set when DOMContentLoaded fires.
    page.add_init_script("""
        window._themeAtDOMReady = null;
        window._overridesAtDOMReady = null;
        document.addEventListener('DOMContentLoaded', function() {
            window._themeAtDOMReady = document.documentElement.getAttribute('data-theme');
            var el = document.getElementById('qm-theme-overrides');
            window._overridesAtDOMReady = el ? el.textContent : '';
        });
    """)

    page.reload()

    theme_at_dom_ready = page.evaluate("window._themeAtDOMReady")
    overrides_at_dom_ready = page.evaluate("window._overridesAtDOMReady")

    try:
        assert theme_at_dom_ready not in (None, ""), (
            f"FOUC DETECTED: data-theme not set at DOMContentLoaded "
            f"(got: {theme_at_dom_ready!r}). The inline FOUC script in <head> is broken."
        )
        assert _CANARY_DARK_BG in (overrides_at_dom_ready or ""), (
            f"Custom color {_CANARY_DARK_BG!r} missing from #qm-theme-overrides at "
            f"DOMContentLoaded. Server-side style injection is not working."
        )
    finally:
        _goto_themes(page)
        page.click(".color-editor .seg-btn:has-text('Dark mode')")
        df = page.locator("form.color-editor-form[data-mode='dark']")
        df.locator("#dark-1").fill(_DEFAULT_DARK_BG)
        with page.expect_response("**/api/settings/themes/**"):
            df.locator("button:has-text('Save')").click()
        expect(page.locator(".theme-list")).to_be_visible(timeout=5000)


@pytest.mark.e2e
def test_mode_preference_auto_follows_os_preference(page: Page):
    """mode_preference='auto' must derive data-theme from prefers-color-scheme on reload."""
    _goto_themes(page)

    auto_radio = page.locator("input[name='mode_preference'][value='auto']")
    if not auto_radio.is_checked():
        with page.expect_response("**/api/settings/themes/**"):
            auto_radio.check()
        expect(page.locator(".theme-list")).to_be_visible(timeout=5000)

    # Dark OS preference
    page.evaluate("try { localStorage.removeItem('qm-theme-override'); } catch(e) {}")
    page.emulate_media(color_scheme="dark")
    page.reload()
    theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert theme == "dark", (
        f"Expected data-theme='dark' with dark OS preference and mode=auto, got {theme!r}"
    )

    # Light OS preference
    page.evaluate("try { localStorage.removeItem('qm-theme-override'); } catch(e) {}")
    page.emulate_media(color_scheme="light")
    page.reload()
    theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert theme == "light", (
        f"Expected data-theme='light' with light OS preference and mode=auto, got {theme!r}"
    )
