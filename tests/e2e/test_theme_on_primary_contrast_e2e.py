"""
E2E test for the derived --brand-on-primary foreground token (Issue #232).

A custom `--brand-primary` is currently emitted with no matching
`--brand-on-primary`, so the settings primary button's text color stays
pinned to a static default (#1c1f24 dark / #ffffff light) picked for the
default teal brand. `#7a7f4a` is a verified hostile color: it scores only
3.90:1 against #1c1f24 and 4.23:1 against #ffffff, so it fails WCAG AA
(4.5:1) against BOTH static defaults.

This test saves #7a7f4a as the dark-mode brand_primary, reloads (the
qm-theme-overrides block is server-rendered at page load), and asserts:

1. Token-level: the computed --brand-on-primary meets >= 4.5:1 against the
   computed --brand-primary.
2. Rendered-button-level: the settings primary button's actual computed
   color vs background-color meets >= 4.5:1.

Expected to FAIL until api/routes.py's load_active_theme() injects a
derived brand_on_primary alongside a custom brand_primary (Issue #232).
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
_HOSTILE_BRAND = "#7a7f4a"
_DEFAULT_DARK_BRAND = "#14b8a6"


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
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip(f"Backend is not running on {BASE_URL} — skipping E2E tests.")
    page.click("button.nav-item:has-text('Settings')")
    expect(page.locator("#settings-pane")).to_be_visible()
    page.click(".settings-sidenav-item[data-section='themes']")
    expect(page.locator(".theme-list")).to_be_visible(timeout=5000)


def _save_dark_brand_primary(page: Page, hex_value: str):
    _goto_themes(page)
    page.click(".color-editor .seg-btn:has-text('Dark mode')")
    dark_form = page.locator("form.color-editor-form[data-mode='dark']")
    # dark-5 = brand_primary (5th in the fixed THEME_COLOR_KEYS allowlist:
    # bg_base, bg_surface, text_primary, text_muted, brand_primary, ...)
    dark_form.locator("#dark-5").fill(hex_value)
    with page.expect_response("**/api/settings/themes/**"):
        dark_form.get_by_role("button", name="Save").click()
    expect(page.locator(".theme-list")).to_be_visible(timeout=5000)


@pytest.mark.e2e
def test_on_primary_meets_wcag_aa_after_hostile_dark_brand_save(page: Page):
    """After saving a hostile dark-mode brand_primary and reloading, both the
    computed --brand-on-primary token and the rendered settings primary
    button must meet WCAG AA (>= 4.5:1) contrast."""
    _save_dark_brand_primary(page, _HOSTILE_BRAND)

    try:
        # Reload so the server-rendered qm-theme-overrides block reflects
        # the saved color, then force dark mode.
        page.reload()
        page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")

        # ── Contract 1: token-level contrast ──
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
            f"--brand-on-primary ({brand_on_primary_hex!r}) vs --brand-primary "
            f"({brand_primary_hex!r}) contrast ratio {token_ratio:.2f} is below "
            f"WCAG AA minimum {WCAG_AA_MIN}"
        )

        # ── Contract 2: rendered settings primary button contrast ──
        # Re-enter the Themes UI (the page reload above reset the settings
        # sub-section) and re-select the Dark mode segment so the dark
        # color-editor form's "Save" button — a `.btn-primary` styled by the
        # settings-scoped rule (`.settings-pane .btn-primary`, which sets
        # `color: var(--brand-on-primary)`) — is actually visible. The
        # locator below is form-scoped and role-based (get_by_role), which
        # matches against the accessibility tree; the hidden (display:none)
        # server-edit-row "Save" button is excluded from that tree, so the
        # ambiguity that `#settings-pane .btn-primary >> nth=0` had cannot
        # arise here.
        _goto_themes(page)
        # _goto_themes() re-navigates via page.goto(), which resets
        # data-theme to its page-default value, discarding the 'dark'
        # forced above. Re-apply and verify it before measuring, otherwise
        # the button below would be measured in light mode.
        page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
        active_theme = page.evaluate(
            "document.documentElement.getAttribute('data-theme')"
        )
        assert active_theme == "dark", (
            f"Expected data-theme='dark' at measurement time, got {active_theme!r}"
        )

        page.click(".color-editor .seg-btn:has-text('Dark mode')")
        dark_form = page.locator("form.color-editor-form[data-mode='dark']")
        button = dark_form.get_by_role("button", name="Save")
        expect(button).to_be_visible()

        button_color = button.evaluate("el => window.getComputedStyle(el).color")
        button_bg = button.evaluate(
            "el => window.getComputedStyle(el).backgroundColor"
        )
        button_color_hex = _normalize_color(button_color)
        button_bg_hex = _normalize_color(button_bg)

        print(
            f"[contract-2] locator=form.color-editor-form[data-mode='dark'] "
            f">> get_by_role('button', name='Save') "
            f"data-theme={active_theme!r} "
            f"color={button_color!r} ({button_color_hex}) "
            f"background-color={button_bg!r} ({button_bg_hex})"
        )

        # Guard: if the locator resolved to the wrong element, or the page
        # were in the wrong theme, the contrast check below would otherwise
        # silently measure a default color pair (e.g. the static light-mode
        # teal) and report a passing ratio without ever exercising the fix.
        # Pin the measured background to the hostile color we actually saved
        # so a wrong-state failure is loud, not a silent vacuous pass.
        expected_bg_hex = _normalize_color(_HOSTILE_BRAND)
        assert button_bg_hex == expected_bg_hex, (
            f"Expected the measured button background-color to be the "
            f"hostile saved brand_primary {expected_bg_hex!r} "
            f"({_HOSTILE_BRAND!r}), but measured {button_bg_hex!r} "
            f"({button_bg!r}) instead — the button/theme state is wrong, "
            f"so the contrast ratio below would not be testing the fix."
        )

        button_ratio = contrast_ratio(button_color_hex, button_bg_hex)
        print(f"[contract-2] ratio={button_ratio:.3f}")
        assert button_ratio >= WCAG_AA_MIN, (
            f"Settings primary button color ({button_color_hex!r}) vs "
            f"background-color ({button_bg_hex!r}) contrast ratio "
            f"{button_ratio:.2f} is below WCAG AA minimum {WCAG_AA_MIN}"
        )
    finally:
        # Restore the dark brand_primary to its default so this test does
        # not poison later e2e runs with a hostile persisted color.
        _save_dark_brand_primary(page, _DEFAULT_DARK_BRAND)
