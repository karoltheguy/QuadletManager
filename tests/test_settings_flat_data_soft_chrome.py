"""
Tests for the "Flat data, soft chrome" restyle of settings tables and forms
(Issue #225).

Today the neumorphic override block near the end of static/style.css
(around line 1747) redefines `.btn-primary` to
`background-color: var(--bg-surface); color: var(--brand-primary);`,
cancelling the earlier solid-fill `.btn-primary` rule
(`background-color: var(--brand-primary);`, around line 812). As a result,
inside #settings-pane the primary and secondary action buttons are visually
indistinguishable except by text color -- there is no flat, solid "data"
affordance, only soft chrome everywhere.

This restyle scopes a solid, flat `.btn-primary` treatment to
`#settings-pane`/`.settings-pane` only (leaving the rest of the app's
buttons, e.g. the terminal Connect / Tail Logs buttons, on the soft
neumorphic treatment), introduces a `--brand-on-primary` foreground token
(defined for both the dark and light theme token blocks) that meets WCAG AA
contrast against `--brand-primary`, and gives settings form controls a
visible border instead of the borderless inset well.

This test module is expected to FAIL until that CSS lands:
  1. No `.settings-pane .btn-primary` (or `#settings-pane .btn-primary`)
     rule exists yet with a solid `var(--brand-primary)` background.
  2. No `--brand-on-primary` token exists yet in either theme block.
  3. (This one already passes today -- it pins the settings-only scoping
     contract: the unscoped `.btn-primary` override must stay soft.)
  4. No `.settings-pane .form-control` (or `#settings-pane .form-control`)
     rule exists yet with a visible border.
"""
import re

import pytest

from tests.css_source import read_static_css


def _css():
    return read_static_css()


# ── Rule-block helpers (same approach as tests/test_design_lint_style.py) ──

def _extract_rule_block(css, selector_regex, start_from=0):
    """Extract the declaration block `{ ... }` body for the FIRST rule whose
    selector matches selector_regex, searching from start_from. Returns
    (block_body, block_end_index) or (None, None) if not found."""
    m = re.search(selector_regex + r"\s*\{", css[start_from:])
    if not m:
        return None, None
    abs_start = start_from + m.end()
    end = css.index("}", abs_start)
    return css[abs_start:end], end


def _extract_last_rule_block(css, selector_regex):
    """Extract the declaration block `{ ... }` body for the LAST rule whose
    selector matches selector_regex exactly (i.e. the rule that wins in the
    cascade because it appears later in the file). Returns block_body or
    None if not found."""
    matches = list(re.finditer(selector_regex + r"\s*\{", css))
    if not matches:
        return None
    m = matches[-1]
    start = m.end()
    end = css.index("}", start)
    return css[start:end]


def _extract_all_tokens(block):
    """Extract ALL `--name: value;` custom property pairs (raw value text,
    not just hex) from a CSS block body."""
    tokens = {}
    if block is None:
        return tokens
    for name, value in re.findall(r"(--[a-zA-Z0-9-]+)\s*:\s*([^;]+);", block):
        tokens[name] = value.strip()
    return tokens


# ── WCAG contrast helpers (same approach as tests/test_brand_teal_contrast.py) ──

def _linearize(channel_0_1: float) -> float:
    if channel_0_1 <= 0.04045:
        return channel_0_1 / 12.92
    return ((channel_0_1 + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
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


_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_VAR_RE = re.compile(r"^var\((--[a-zA-Z0-9-]+)\)$")


def _resolve_token_to_hex(name, tokens, _seen=None):
    """Resolve a custom property to a hex color string, following a single
    level of `var(--other-token)` indirection within the same block. Returns
    None if the token is absent or does not resolve to a hex color."""
    _seen = _seen or set()
    if name in _seen or name not in tokens:
        return None
    _seen = _seen | {name}
    value = tokens[name].strip()
    m_var = _VAR_RE.match(value)
    if m_var:
        return _resolve_token_to_hex(m_var.group(1), tokens, _seen)
    if _HEX_RE.match(value):
        return value
    return None


# ── 1. Settings-scoped .btn-primary should be a solid, flat fill ───────────

class TestSettingsBtnPrimaryUsesSolidBrandFill:
    def setup_method(self):
        self.css = _css()
        self.block, _ = _extract_rule_block(
            self.css,
            r"(?:\.settings-pane|#settings-pane)\s+\.btn-primary",
        )

    @pytest.mark.unit
    def test_settings_btn_primary_rule_exists(self):
        assert self.block is not None, (
            "Expected a '.settings-pane .btn-primary' (or "
            "'#settings-pane .btn-primary') rule in static/style.css scoping "
            "a solid, flat primary-button treatment to the settings pane -- "
            "none was found"
        )

    @pytest.mark.unit
    def test_settings_btn_primary_background_is_solid_brand_not_soft_surface(self):
        assert self.block is not None, (
            "Expected a '.settings-pane .btn-primary' rule to exist so its "
            "background can be checked"
        )
        assert re.search(r"background(?:-color)?\s*:\s*var\(--brand-primary\)", self.block), (
            "'.settings-pane .btn-primary' should set a solid "
            "'var(--brand-primary)' background, not inherit the soft "
            "'var(--bg-surface)' neumorphic override"
        )
        assert "var(--bg-surface)" not in self.block, (
            "'.settings-pane .btn-primary' should not use the soft "
            "'var(--bg-surface)' background"
        )


# ── 2. --brand-on-primary token must exist and meet WCAG AA in both themes ──

class TestBrandOnPrimaryTokenMeetsWcagAa:
    def setup_method(self):
        self.css = _css()
        dark_block, _ = _extract_rule_block(
            self.css, r':root,\s*:root\[data-theme="dark"\]'
        )
        light_block, _ = _extract_rule_block(
            self.css, r':root\[data-theme="light"\]'
        )
        assert dark_block is not None, "Could not find dark :root token block in style.css"
        assert light_block is not None, "Could not find light :root token block in style.css"
        self.dark_tokens = _extract_all_tokens(dark_block)
        self.light_tokens = _extract_all_tokens(light_block)

    @pytest.mark.unit
    def test_dark_theme_defines_brand_on_primary(self):
        assert "--brand-on-primary" in self.dark_tokens, (
            "Expected '--brand-on-primary' to be defined in the dark "
            ":root token block of static/style.css"
        )

    @pytest.mark.unit
    def test_light_theme_defines_brand_on_primary(self):
        assert "--brand-on-primary" in self.light_tokens, (
            "Expected '--brand-on-primary' to be defined in the light "
            ':root[data-theme="light"] token block of static/style.css'
        )

    @pytest.mark.unit
    def test_dark_theme_brand_on_primary_meets_wcag_aa_against_brand_primary(self):
        assert "--brand-on-primary" in self.dark_tokens, (
            "Expected '--brand-on-primary' to be defined in the dark token "
            "block so its contrast against --brand-primary can be checked"
        )
        fg = _resolve_token_to_hex("--brand-on-primary", self.dark_tokens)
        bg = _resolve_token_to_hex("--brand-primary", self.dark_tokens)
        assert fg is not None, (
            "[dark] --brand-on-primary did not resolve to a hex color"
        )
        assert bg is not None, "[dark] --brand-primary did not resolve to a hex color"
        ratio = contrast_ratio(fg, bg)
        assert ratio >= WCAG_AA_MIN, (
            f"[dark] --brand-on-primary ({fg}) vs --brand-primary ({bg}) "
            f"contrast ratio {ratio:.2f} is below WCAG AA minimum {WCAG_AA_MIN}"
        )

    @pytest.mark.unit
    def test_light_theme_brand_on_primary_meets_wcag_aa_against_brand_primary(self):
        assert "--brand-on-primary" in self.light_tokens, (
            "Expected '--brand-on-primary' to be defined in the light token "
            "block so its contrast against --brand-primary can be checked"
        )
        fg = _resolve_token_to_hex("--brand-on-primary", self.light_tokens)
        bg = _resolve_token_to_hex("--brand-primary", self.light_tokens)
        assert fg is not None, (
            "[light] --brand-on-primary did not resolve to a hex color"
        )
        assert bg is not None, "[light] --brand-primary did not resolve to a hex color"
        ratio = contrast_ratio(fg, bg)
        assert ratio >= WCAG_AA_MIN, (
            f"[light] --brand-on-primary ({fg}) vs --brand-primary ({bg}) "
            f"contrast ratio {ratio:.2f} is below WCAG AA minimum {WCAG_AA_MIN}"
        )


# ── 3. The unscoped .btn-primary override must stay soft (scoping guard) ───
#
# This pins the "settings-only scoping" contract: fixing #225 must not make
# the app-wide '.btn-primary' (e.g. the terminal Connect / Tail Logs buttons
# at templates/dashboard.html:491/:505) solid too. This assertion already
# holds against today's CSS -- it is a guard against scope creep, not part
# of the red/failing set.

class TestUnscopedBtnPrimaryStaysSoft:
    def setup_method(self):
        self.css = _css()
        self.block = _extract_last_rule_block(self.css, r"(?m)^\.btn-primary")

    @pytest.mark.unit
    def test_unscoped_btn_primary_still_uses_soft_surface_background(self):
        assert self.block is not None, "No '.btn-primary' rule found in style.css"
        assert re.search(
            r"background(?:-color)?\s*:\s*var\(--bg-surface\)", self.block
        ), (
            "The unscoped '.btn-primary' rule (app chrome, e.g. terminal "
            "Connect / Tail Logs buttons) should keep its soft "
            "'var(--bg-surface)' background -- the flat, solid treatment "
            "must be scoped to #settings-pane only"
        )


# ── 4. Settings-scoped .form-control should have a visible border ─────────

class TestSettingsFormControlHasVisibleBorder:
    def setup_method(self):
        self.css = _css()
        self.block, _ = _extract_rule_block(
            self.css,
            r"(?:\.settings-pane|#settings-pane)\s+\.form-control",
        )

    @pytest.mark.unit
    def test_settings_form_control_rule_exists(self):
        assert self.block is not None, (
            "Expected a '.settings-pane .form-control' (or "
            "'#settings-pane .form-control') rule in static/style.css -- "
            "none was found"
        )

    @pytest.mark.unit
    def test_settings_form_control_declares_a_visible_border(self):
        assert self.block is not None, (
            "Expected a '.settings-pane .form-control' rule to exist so its "
            "border can be checked"
        )
        m = re.search(r"\bborder\s*:\s*([^;]+);", self.block)
        assert m is not None, (
            "'.settings-pane .form-control' should declare a 'border:' "
            "instead of relying on the borderless inset well"
        )
        assert m.group(1).strip() != "none", (
            "'.settings-pane .form-control' border should not be 'none'"
        )
