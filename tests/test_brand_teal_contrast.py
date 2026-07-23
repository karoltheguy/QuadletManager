"""
Tests for WCAG AA contrast of the brand teal tokens (Issue #223).

The light-mode brand teal `--brand-primary` / `--text-accent` (#0d9488)
measures well under the WCAG AA 4.5:1 threshold against the light
neumorphism backgrounds, and the dark-mode `--brand-hover` (also #0d9488)
likewise fails against the dark backgrounds. These tests parse the real
CSS/template/route sources (no hardcoded "fixed" values) and assert
contrast >= 4.5:1 for the brand teal foreground tokens against each
background token defined in the same block.

This test is expected to FAIL until the teal tokens are darkened
(light mode) / lightened (dark mode) to meet WCAG AA.
"""
import os
import re

import pytest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
CSS_PATH = os.path.join(REPO_ROOT, "static", "style.css")
LOGIN_PATH = os.path.join(REPO_ROOT, "templates", "login.html")
CHANGE_PW_PATH = os.path.join(REPO_ROOT, "templates", "change_password.html")
ROUTES_PATH = os.path.join(REPO_ROOT, "api", "routes.py")

FOREGROUND_TOKENS = ("--brand-primary", "--text-accent", "--brand-hover")
BACKGROUND_TOKENS = ("--bg-base", "--bg-surface", "--bg-element")


# ── WCAG contrast helpers ─────────────────────────────────────

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


# ── Source parsing helpers ────────────────────────────────────

def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _extract_rule_block(css: str, selector_regex: str, start_from: int = 0):
    """Extract the declaration block `{ ... }` body for the first rule whose
    selector matches selector_regex, searching from start_from. Returns
    (block_body, block_end_index) or (None, None) if not found."""
    m = re.search(selector_regex + r"\s*\{", css[start_from:])
    if not m:
        return None, None
    abs_start = start_from + m.end()
    end = css.index("}", abs_start)
    return css[abs_start:end], end


def _extract_media_block(css: str, media_regex: str):
    m = re.search(media_regex + r"\s*\{", css)
    if not m:
        return None
    depth = 1
    i = m.end()
    start = i
    while depth > 0 and i < len(css):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
        i += 1
    return css[start:i - 1]


def _extract_tokens(block: str) -> dict:
    """Extract `--name: #hex;` custom property pairs from a CSS block body."""
    tokens = {}
    for name, value in re.findall(r"(--[a-zA-Z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", block):
        tokens[name] = value
    return tokens


def _load_style_css_blocks():
    css = _read(CSS_PATH)

    dark_block, _ = _extract_rule_block(
        css, r':root,\s*:root\[data-theme="dark"\]'
    )
    assert dark_block is not None, "Could not find dark :root token block in style.css"

    light_block, _ = _extract_rule_block(css, r':root\[data-theme="light"\]')
    assert light_block is not None, "Could not find light :root token block in style.css"

    media_block = _extract_media_block(
        css, r"@media\s*\(\s*prefers-color-scheme\s*:\s*light\s*\)"
    )
    assert media_block is not None, "Could not find prefers-color-scheme: light media block"
    os_light_block, _ = _extract_rule_block(media_block, r':root:not\(\[data-theme\]\)')
    assert os_light_block is not None, "Could not find :root:not([data-theme]) block inside prefers-color-scheme: light"

    return {
        "dark": _extract_tokens(dark_block),
        "light": _extract_tokens(light_block),
        "os_light": _extract_tokens(os_light_block),
    }


def _load_template_light_block(path: str) -> dict:
    html = _read(path)
    block, _ = _extract_rule_block(html, r':root\[data-theme="light"\]')
    assert block is not None, f"Could not find :root[data-theme=\"light\"] block in {path}"
    return _extract_tokens(block)


def _load_routes_default_colors(dict_name: str) -> dict:
    text = _read(ROUTES_PATH)
    m = re.search(re.escape(dict_name) + r"\s*=\s*\{(.*?)\}", text, re.DOTALL)
    assert m is not None, f"Could not find {dict_name} dict in api/routes.py"
    body = m.group(1)
    colors = {}
    for key, value in re.findall(r'"(\w+)"\s*:\s*"(#[0-9a-fA-F]{6})"', body):
        colors[key] = value
    return colors


# ── Pairs to check for the three style.css token blocks ───────

def _pairs_for_block(block_name: str, tokens: dict):
    """Yield (fg_name, fg_hex, bg_name, bg_hex) for tokens present in the block."""
    pairs = []
    for fg in FOREGROUND_TOKENS:
        if fg not in tokens:
            continue
        for bg in BACKGROUND_TOKENS:
            if bg not in tokens:
                continue
            pairs.append((fg, tokens[fg], bg, tokens[bg]))
    return pairs


_STYLE_BLOCKS = _load_style_css_blocks()

_LIGHT_PAIRS = _pairs_for_block("light", _STYLE_BLOCKS["light"])
_OS_LIGHT_PAIRS = _pairs_for_block("os_light", _STYLE_BLOCKS["os_light"])
_DARK_PAIRS = _pairs_for_block("dark", _STYLE_BLOCKS["dark"])


def _pair_id(pair):
    fg_name, fg_hex, bg_name, bg_hex = pair
    return f"{fg_name}({fg_hex})_vs_{bg_name}({bg_hex})"


@pytest.mark.parametrize("pair", _LIGHT_PAIRS, ids=_pair_id)
def test_light_theme_brand_tokens_meet_wcag_aa(pair):
    fg_name, fg_hex, bg_name, bg_hex = pair
    ratio = contrast_ratio(fg_hex, bg_hex)
    assert ratio >= WCAG_AA_MIN, (
        f"[:root[data-theme=\"light\"]] {fg_name} ({fg_hex}) vs {bg_name} ({bg_hex}) "
        f"contrast ratio {ratio:.2f} is below WCAG AA minimum {WCAG_AA_MIN}"
    )


@pytest.mark.parametrize("pair", _OS_LIGHT_PAIRS, ids=_pair_id)
def test_os_preference_light_theme_brand_tokens_meet_wcag_aa(pair):
    fg_name, fg_hex, bg_name, bg_hex = pair
    ratio = contrast_ratio(fg_hex, bg_hex)
    assert ratio >= WCAG_AA_MIN, (
        f"[prefers-color-scheme: light :root:not([data-theme])] {fg_name} ({fg_hex}) "
        f"vs {bg_name} ({bg_hex}) contrast ratio {ratio:.2f} is below WCAG AA minimum {WCAG_AA_MIN}"
    )


@pytest.mark.parametrize("pair", _DARK_PAIRS, ids=_pair_id)
def test_dark_theme_brand_tokens_meet_wcag_aa(pair):
    fg_name, fg_hex, bg_name, bg_hex = pair
    ratio = contrast_ratio(fg_hex, bg_hex)
    assert ratio >= WCAG_AA_MIN, (
        f"[:root[data-theme=\"dark\"]] {fg_name} ({fg_hex}) vs {bg_name} ({bg_hex}) "
        f"contrast ratio {ratio:.2f} is below WCAG AA minimum {WCAG_AA_MIN}"
    )


# ── Standalone light-mode blocks in login.html / change_password.html ─

_TEMPLATE_BG_TOKENS = ("--bg-base", "--bg-surface")


def _template_pairs(tokens: dict):
    pairs = []
    if "--brand-primary" not in tokens:
        return pairs
    for bg in _TEMPLATE_BG_TOKENS:
        if bg not in tokens:
            continue
        pairs.append(("--brand-primary", tokens["--brand-primary"], bg, tokens[bg]))
    return pairs


_LOGIN_TOKENS = _load_template_light_block(LOGIN_PATH)
_CHANGE_PW_TOKENS = _load_template_light_block(CHANGE_PW_PATH)

_LOGIN_PAIRS = _template_pairs(_LOGIN_TOKENS)
_CHANGE_PW_PAIRS = _template_pairs(_CHANGE_PW_TOKENS)


@pytest.mark.parametrize("pair", _LOGIN_PAIRS, ids=_pair_id)
def test_login_template_light_brand_primary_meets_wcag_aa(pair):
    fg_name, fg_hex, bg_name, bg_hex = pair
    ratio = contrast_ratio(fg_hex, bg_hex)
    assert ratio >= WCAG_AA_MIN, (
        f"[templates/login.html :root[data-theme=\"light\"]] {fg_name} ({fg_hex}) "
        f"vs {bg_name} ({bg_hex}) contrast ratio {ratio:.2f} is below WCAG AA minimum {WCAG_AA_MIN}"
    )


@pytest.mark.parametrize("pair", _CHANGE_PW_PAIRS, ids=_pair_id)
def test_change_password_template_light_brand_primary_meets_wcag_aa(pair):
    fg_name, fg_hex, bg_name, bg_hex = pair
    ratio = contrast_ratio(fg_hex, bg_hex)
    assert ratio >= WCAG_AA_MIN, (
        f"[templates/change_password.html :root[data-theme=\"light\"]] {fg_name} ({fg_hex}) "
        f"vs {bg_name} ({bg_hex}) contrast ratio {ratio:.2f} is below WCAG AA minimum {WCAG_AA_MIN}"
    )


# ── api/routes.py _DEFAULT_COLORS_LIGHT ────────────────────────

_ROUTES_LIGHT_COLORS = _load_routes_default_colors("_DEFAULT_COLORS_LIGHT")
_ROUTES_DARK_COLORS = _load_routes_default_colors("_DEFAULT_COLORS_DARK")
_ROUTES_BG_KEYS = ("bg_base", "bg_surface")


def _routes_pairs():
    pairs = []
    if "brand_primary" not in _ROUTES_LIGHT_COLORS:
        return pairs
    for bg_key in _ROUTES_BG_KEYS:
        if bg_key not in _ROUTES_LIGHT_COLORS:
            continue
        pairs.append((
            "brand_primary", _ROUTES_LIGHT_COLORS["brand_primary"],
            bg_key, _ROUTES_LIGHT_COLORS[bg_key],
        ))
    return pairs


_ROUTES_PAIRS = _routes_pairs()


@pytest.mark.parametrize("pair", _ROUTES_PAIRS, ids=_pair_id)
def test_routes_default_colors_light_brand_primary_meets_wcag_aa(pair):
    fg_name, fg_hex, bg_name, bg_hex = pair
    ratio = contrast_ratio(fg_hex, bg_hex)
    assert ratio >= WCAG_AA_MIN, (
        f"[api/routes.py _DEFAULT_COLORS_LIGHT] {fg_name} ({fg_hex}) vs {bg_name} ({bg_hex}) "
        f"contrast ratio {ratio:.2f} is below WCAG AA minimum {WCAG_AA_MIN}"
    )


# ── Structural guard: catch silent vacuous-pass from a token/selector rename ─
#
# The contrast tests above are parametrized from tokens that are present in
# each parsed block; a token that is silently absent (e.g. because it was
# renamed, or a selector regex stopped matching) is simply skipped rather
# than causing a failure, so the parametrized tests would keep "passing"
# with zero cases. This test asserts the expected tokens were actually
# found in each source/block, so a rename breaks loudly here instead.

_STYLE_CSS_BLOCK_TOKENS = ("--brand-primary", "--brand-hover", "--text-accent",
                            "--bg-base", "--bg-surface", "--bg-element")

_TEMPLATE_LIGHT_BLOCK_TOKENS = ("--brand-primary", "--bg-base", "--bg-surface")

_ROUTES_LIGHT_DICT_KEYS = ("brand_primary", "bg_base", "bg_surface")


def test_parsed_sources_yielded_expected_tokens():
    """Guard against a rename making the regexes match nothing, which
    would otherwise let the parametrized WCAG tests above pass vacuously
    (an absent token is skipped, not failed)."""
    for block_name, tokens in (
        ('style.css :root,:root[data-theme="dark"]', _STYLE_BLOCKS["dark"]),
        ('style.css :root[data-theme="light"]', _STYLE_BLOCKS["light"]),
        ('style.css prefers-color-scheme:light :root:not([data-theme])', _STYLE_BLOCKS["os_light"]),
    ):
        for token in _STYLE_CSS_BLOCK_TOKENS:
            assert token in tokens, (
                f"Expected token {token!r} not found in block [{block_name}] "
                f"of {CSS_PATH} -- a rename or selector change likely broke parsing"
            )

    for path_name, path, tokens in (
        ("templates/login.html", LOGIN_PATH, _LOGIN_TOKENS),
        ("templates/change_password.html", CHANGE_PW_PATH, _CHANGE_PW_TOKENS),
    ):
        for token in _TEMPLATE_LIGHT_BLOCK_TOKENS:
            assert token in tokens, (
                f"Expected token {token!r} not found in :root[data-theme=\"light\"] "
                f"block of {path_name} ({path}) -- a rename or selector change "
                f"likely broke parsing"
            )

    for key in _ROUTES_LIGHT_DICT_KEYS:
        assert key in _ROUTES_LIGHT_COLORS, (
            f"Expected key {key!r} not found in _DEFAULT_COLORS_LIGHT of "
            f"{ROUTES_PATH} -- a rename likely broke parsing"
        )


# ── Lockstep guards: the same brand value must appear everywhere ──────
#
# The contrast tests above check each source independently, so two sources
# could drift to *different* (both individually passing) teals without any
# test noticing. These tests pin the cross-source equality contract: the
# prefers-color-scheme fallback, the standalone template blocks, and the
# api/routes.py default palettes must all carry the same brand values as
# the corresponding style.css token blocks.

_LOCKSTEP_BRAND_TOKENS = ("--brand-primary", "--brand-hover", "--text-accent")


@pytest.mark.parametrize("token", _LOCKSTEP_BRAND_TOKENS)
def test_os_light_fallback_brand_tokens_match_light_block(token):
    light_value = _STYLE_BLOCKS["light"][token]
    os_light_value = _STYLE_BLOCKS["os_light"][token]
    assert os_light_value == light_value, (
        f"[prefers-color-scheme: light :root:not([data-theme])] {token} "
        f"({os_light_value}) does not match [:root[data-theme=\"light\"]] "
        f"{token} ({light_value})"
    )


@pytest.mark.parametrize("path_name,tokens", [
    ("templates/login.html", _LOGIN_TOKENS),
    ("templates/change_password.html", _CHANGE_PW_TOKENS),
], ids=lambda v: v if isinstance(v, str) else "")
def test_template_light_brand_primary_matches_style_css(path_name, tokens):
    light_value = _STYLE_BLOCKS["light"]["--brand-primary"]
    template_value = tokens["--brand-primary"]
    assert template_value == light_value, (
        f"[{path_name} :root[data-theme=\"light\"]] --brand-primary "
        f"({template_value}) does not match style.css light --brand-primary "
        f"({light_value})"
    )


@pytest.mark.parametrize("dict_name,colors,block_name", [
    ("_DEFAULT_COLORS_LIGHT", _ROUTES_LIGHT_COLORS, "light"),
    ("_DEFAULT_COLORS_DARK", _ROUTES_DARK_COLORS, "dark"),
], ids=["light", "dark"])
def test_routes_default_brand_primary_matches_style_css(dict_name, colors, block_name):
    css_value = _STYLE_BLOCKS[block_name]["--brand-primary"]
    routes_value = colors.get("brand_primary")
    assert routes_value == css_value, (
        f"[api/routes.py {dict_name}] brand_primary ({routes_value}) does not "
        f"match style.css {block_name} --brand-primary ({css_value})"
    )


# ── Hover-darkens relationship (light theme) ──────────────────────────
#
# In light mode --brand-hover reads as a *pressed/darker* state of
# --brand-primary; a fix that darkened primary past hover would silently
# invert that relationship.

def test_light_brand_hover_is_darker_than_brand_primary():
    primary = _STYLE_BLOCKS["light"]["--brand-primary"]
    hover = _STYLE_BLOCKS["light"]["--brand-hover"]
    l_primary = relative_luminance(primary)
    l_hover = relative_luminance(hover)
    assert l_hover < l_primary, (
        f"Expected light --brand-hover ({hover}, L={l_hover:.4f}) to be darker "
        f"(lower relative luminance) than --brand-primary ({primary}, "
        f"L={l_primary:.4f}) to preserve the hover-darkens relationship"
    )
