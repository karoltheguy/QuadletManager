"""
E2E tests for the Settings "flat data, soft chrome" UI depth model (Issue #225).

A sibling unit test (tests/test_settings_flat_data_soft_chrome.py) greps
static/style.css as TEXT, which cannot prove the cascade actually resolves:
style.css has TWO competing `.btn-primary` blocks roughly 900 lines apart
(an early block with a real `var(--brand-primary)` fill, and a later
neumorphic override setting `background-color: var(--bg-surface)` that wins
today). These tests assert COMPUTED styles via getComputedStyle so they
catch specificity/ordering mistakes the text test cannot see.
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

BASE_URL = "http://localhost:8000"


# ── WCAG contrast helpers (mirrors tests/test_brand_teal_contrast.py) ──

def _parse_rgb(rgb_str: str):
    """Parse an 'rgb(r, g, b)' or 'rgba(r, g, b, a)' string into (r, g, b) ints."""
    inner = rgb_str[rgb_str.index("(") + 1: rgb_str.index(")")]
    parts = [p.strip() for p in inner.split(",")]
    r, g, b = int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
    return r, g, b


def _hex_to_rgb(hex_str: str):
    hex_str = hex_str.strip().lstrip("#")
    if len(hex_str) == 3:
        hex_str = "".join(ch * 2 for ch in hex_str)
    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)
    return r, g, b


def _normalize_to_rgb_tuple(value: str):
    """Normalize either an rgb()/rgba() string or a #hex string to (r, g, b)."""
    value = value.strip()
    if value.startswith("#"):
        return _hex_to_rgb(value)
    return _parse_rgb(value)


def _linearize(channel_0_1: float) -> float:
    if channel_0_1 <= 0.04045:
        return channel_0_1 / 12.92
    return ((channel_0_1 + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb_tuple) -> float:
    r, g, b = (c / 255 for c in rgb_tuple)
    r, g, b = _linearize(r), _linearize(g), _linearize(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(rgb_a, rgb_b) -> float:
    la = _relative_luminance(rgb_a)
    lb = _relative_luminance(rgb_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


WCAG_AA_MIN = 4.5


def _goto_settings(page: Page):
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")
    # `.btn` transitions `color` (and box-shadow/transform) but not
    # `background-color` (see static/style.css). When a test switches
    # data-theme, the background snaps to the new theme instantly while
    # `color` is still interpolating from its previous value, so a
    # getComputedStyle read on the next tick can catch a mid-transition
    # frame instead of the settled value. WCAG contrast is a statement
    # about the settled state, so suppress transitions/animations for the
    # page before any assertions run.
    page.add_style_tag(
        content="*, *::before, *::after { transition: none !important; animation: none !important; }"
    )
    page.click("button.nav-item:has-text('Settings')")
    expect(page.locator("#settings-pane")).to_be_visible()


def _computed_bg(page: Page, selector: str) -> str:
    return page.evaluate(
        "window.getComputedStyle(document.querySelector(%r)).backgroundColor" % selector
    )


def _computed_color(page: Page, selector: str) -> str:
    return page.evaluate(
        "window.getComputedStyle(document.querySelector(%r)).color" % selector
    )


def _brand_primary_value(page: Page) -> str:
    return page.evaluate(
        "window.getComputedStyle(document.documentElement)"
        ".getPropertyValue('--brand-primary').trim()"
    )


@pytest.mark.e2e
def test_settings_add_server_button_has_real_brand_fill(page: Page):
    """The settings submit button must resolve to a real --brand-primary fill,
    not the soft neumorphic --bg-surface treatment, once the cascade is
    actually resolved by the browser."""
    _goto_settings(page)

    # Scoped to the always-visible "Add Server" form rather than the bare
    # "#settings-pane button.btn-primary", which also matches the per-row
    # inline-edit "Save" buttons that stay `display:none` until "Edit" is
    # clicked. `.first` on the unscoped selector resolves to one of those
    # hidden buttons, which is an infrastructure/selector problem distinct
    # from the CSS fill defect this test targets.
    button_selector = "#settings-pane .add-server-form button.btn-primary"
    expect(page.locator(button_selector).first).to_be_visible()

    button_bg = _computed_bg(page, button_selector)
    panel_bg = _computed_bg(page, "#settings-pane")
    brand_primary_raw = _brand_primary_value(page)

    assert button_bg != panel_bg, (
        f"Expected #settings-pane button.btn-primary background-color "
        f"({button_bg!r}) to differ from the settings panel surface "
        f"({panel_bg!r}), i.e. a real fill rather than the soft --bg-surface "
        f"treatment"
    )

    button_rgb = _normalize_to_rgb_tuple(button_bg)
    brand_rgb = _normalize_to_rgb_tuple(brand_primary_raw)
    assert button_rgb == brand_rgb, (
        f"Expected #settings-pane button.btn-primary background-color "
        f"{button_bg!r} to equal computed --brand-primary "
        f"({brand_primary_raw!r} -> rgb{brand_rgb}), got rgb{button_rgb}"
    )


@pytest.mark.e2e
@pytest.mark.parametrize("theme", ["default", "light", "dark"])
def test_settings_add_server_button_meets_wcag_aa_contrast(page: Page, theme: str):
    """The settings submit button's text-on-fill contrast must meet WCAG AA
    (>= 4.5:1) in the default theme as well as after switching to light and
    dark mode."""
    _goto_settings(page)

    # See test_settings_add_server_button_has_real_brand_fill for why this is
    # scoped to .add-server-form rather than the bare selector.
    button_selector = "#settings-pane .add-server-form button.btn-primary"
    expect(page.locator(button_selector).first).to_be_visible()

    if theme != "default":
        page.evaluate(
            "document.documentElement.setAttribute('data-theme', %r)" % theme
        )

    button_bg = _computed_bg(page, button_selector)
    button_fg = _computed_color(page, button_selector)

    bg_rgb = _normalize_to_rgb_tuple(button_bg)
    fg_rgb = _normalize_to_rgb_tuple(button_fg)
    ratio = _contrast_ratio(fg_rgb, bg_rgb)

    assert ratio >= WCAG_AA_MIN, (
        f"[theme={theme}] #settings-pane button.btn-primary contrast ratio "
        f"{ratio:.2f} (color={button_fg!r} vs background-color={button_bg!r}) "
        f"is below WCAG AA minimum {WCAG_AA_MIN}"
    )


@pytest.mark.e2e
def test_settings_input_has_visible_border(page: Page):
    """A settings form-control input must have a real visible border
    (flat data surfaces still need a discernible input boundary), not
    border-style: none / border-top-width: 0px."""
    _goto_settings(page)

    # Scoped to the always-visible "Add Server" form for the same reason as
    # the button selector above: the bare selector's `.first` resolves to a
    # hidden per-row inline-edit input.
    input_selector = "#settings-pane .add-server-form input.form-control"
    expect(page.locator(input_selector).first).to_be_visible()

    border_style = page.evaluate(
        "window.getComputedStyle(document.querySelector(%r)).borderStyle" % input_selector
    )
    border_top_width = page.evaluate(
        "window.getComputedStyle(document.querySelector(%r)).borderTopWidth" % input_selector
    )

    assert border_style != "none", (
        f"Expected {input_selector} computed border-style to not be 'none', "
        f"got {border_style!r}"
    )
    assert border_top_width != "0px", (
        f"Expected {input_selector} computed border-top-width to not be "
        f"'0px', got {border_top_width!r}"
    )


@pytest.mark.e2e
def test_non_settings_primary_button_keeps_soft_surface_scoping(page: Page):
    """Scoping guard: the flat-data fill must be scoped to settings only.
    A non-settings primary button (#terminal-connect-btn, outside
    #settings-pane) must still resolve to the soft --bg-surface treatment,
    not the brand-primary fill."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")

    button = page.locator("#terminal-connect-btn")
    if button.count() == 0:
        pytest.skip(
            "#terminal-connect-btn could not be located in the DOM; "
            "skipping scoping guard rather than deleting it."
        )

    button_bg = button.evaluate("el => window.getComputedStyle(el).backgroundColor")
    brand_primary_raw = _brand_primary_value(page)

    button_rgb = _normalize_to_rgb_tuple(button_bg)
    brand_rgb = _normalize_to_rgb_tuple(brand_primary_raw)

    assert button_rgb != brand_rgb, (
        f"Expected #terminal-connect-btn background-color ({button_bg!r} -> "
        f"rgb{button_rgb}) to NOT equal --brand-primary "
        f"({brand_primary_raw!r} -> rgb{brand_rgb}); the flat-data fill must "
        f"be scoped to #settings-pane only"
    )
