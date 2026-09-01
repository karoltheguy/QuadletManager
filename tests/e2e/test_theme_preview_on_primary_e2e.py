"""
E2E test for the theme customization *preview* path emitting a derived
--brand-on-primary foreground token (Issue #233).

Unlike tests/e2e/test_theme_on_primary_contrast_e2e.py (Issue #232), which
covers the SAVED theme, this test exercises the live client-side PREVIEW:
filling a color picker and clicking the form's "Preview" button
(`onclick="applyThemePreview(this.closest('form'))"`) WITHOUT saving.

`#7a7f4a` is a verified hostile color: it scores only 3.90:1 against
#1c1f24 and 4.23:1 against #ffffff, so it fails WCAG AA (4.5:1) against
BOTH static defaults. This test fills the dark form's `#dark-5`
(brand_primary) with `#7a7f4a`, clicks Preview, and asserts the computed
`--brand-on-primary` vs `--brand-primary` on `document.documentElement`
clears 4.5:1.

Expected to FAIL until static/main.js's applyThemePreview() derives and
emits a WCAG-AA-compliant --brand-on-primary (Issue #233).

NOTE: the backend is not running at QM_APP_URL in CI/dev sandboxes, so
this test is expected to SKIP via _goto_themes()'s page.goto() guard.
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

from tests.e2e.app_page import goto_app
_HOSTILE_BRAND = "#7a7f4a"


# ── WCAG contrast helpers (copied from tests/test_brand_teal_contrast.py
#    lines 32-54; cross-package import from tests/e2e/ is awkward) ──

def _linearize(channel_0_1: float) -> float:
    if channel_0_1 <= 0.04045:
        return channel_0_1 / 12.92
    return ((channel_0_1 + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255
    g = int(hex_color[2:4], 16) / 255
    b = int(hex_color[4:6], 16) / 255
    r, g, b = _linearize(r), _linearize(g), _linearize(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la = relative_luminance(hex_a)
    lb = relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


WCAG_AA_MIN = 4.5


def _normalize_color(value: str) -> str:
    """Normalize a CSS color string (hex or rgb(...)) to '#rrggbb'."""
    value = value.strip()
    if value.startswith("#"):
        if len(value) == 4:
            # #abc -> #aabbcc
            return "#" + "".join(c * 2 for c in value[1:])
        return value.lower()
    if value.startswith("rgb"):
        nums = value[value.index("(") + 1:value.index(")")].split(",")
        r, g, b = (int(float(n.strip())) for n in nums[:3])
        return f"#{r:02x}{g:02x}{b:02x}"
    raise ValueError(f"Unrecognized color format: {value!r}")


def _goto_themes(page: Page):
    goto_app(page)
    page.click("button.nav-item:has-text('Settings')")
    expect(page.locator("#settings-pane")).to_be_visible()
    page.click(".settings-sidenav-item[data-section='themes']")
    expect(page.locator(".theme-list")).to_be_visible(timeout=5000)


@pytest.mark.e2e
def test_on_primary_meets_wcag_aa_after_hostile_dark_brand_preview(page: Page):
    """Filling the dark form's brand_primary picker with a hostile color and
    clicking Preview (without saving) must derive a --brand-on-primary that
    meets WCAG AA (>= 4.5:1) contrast against the previewed --brand-primary."""
    _goto_themes(page)

    page.click(".color-editor .seg-btn:has-text('Dark mode')")
    dark_form = page.locator("form.color-editor-form[data-mode='dark']")
    # dark-5 = brand_primary (5th in the fixed THEME_COLOR_KEYS allowlist:
    # bg_base, bg_surface, text_primary, text_muted, brand_primary, ...)
    dark_form.locator("#dark-5").fill(_HOSTILE_BRAND)

    # exact=True is load-bearing: get_by_role's name match is substring-based,
    # so a bare name="Preview" also matches this form's "Cancel preview"
    # button and trips Playwright's strict mode. (Same selector hazard as #234.)
    dark_form.get_by_role("button", name="Preview", exact=True).click()

    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")

    brand_primary = page.evaluate(
        "window.getComputedStyle(document.documentElement)"
        ".getPropertyValue('--brand-primary').trim()"
    )
    brand_on_primary = page.evaluate(
        "window.getComputedStyle(document.documentElement)"
        ".getPropertyValue('--brand-on-primary').trim()"
    )
    brand_primary_hex = _normalize_color(brand_primary)
    brand_on_primary_hex = _normalize_color(brand_on_primary)

    token_ratio = contrast_ratio(brand_on_primary_hex, brand_primary_hex)
    assert token_ratio >= WCAG_AA_MIN, (
        f"After previewing (not saving) brand_primary={_HOSTILE_BRAND!r}, "
        f"--brand-on-primary ({brand_on_primary_hex!r}) vs --brand-primary "
        f"({brand_primary_hex!r}) contrast ratio {token_ratio:.2f} is below "
        f"WCAG AA minimum {WCAG_AA_MIN}"
    )


@pytest.mark.e2e
def test_cancel_preview_removes_the_preview_style_element(page: Page):
    """Cancel preview must drop the injected #qm-theme-preview style (#418).

    The Preview and Cancel preview buttons became delegated 'apply-theme-preview'
    and 'clear-theme-preview' actions. Preview is covered by the test above;
    without this one, a broken 'clear-theme-preview' key would leave the button
    inert with every unit test still green.
    """
    _goto_themes(page)

    page.click(".color-editor .seg-btn:has-text('Dark mode')")
    dark_form = page.locator("form.color-editor-form[data-mode='dark']")
    dark_form.locator("#dark-5").fill(_HOSTILE_BRAND)
    dark_form.get_by_role("button", name="Preview", exact=True).click()

    assert page.locator("#qm-theme-preview").count() == 1, (
        "Expected Preview to inject a #qm-theme-preview style element."
    )

    dark_form.get_by_role("button", name="Cancel preview", exact=True).click()

    assert page.locator("#qm-theme-preview").count() == 0, (
        "Expected Cancel preview to remove the #qm-theme-preview style element. "
        "The 'clear-theme-preview' delegated action is not reaching its handler."
    )
