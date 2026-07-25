"""
Tests for the derived --brand-on-primary foreground token (Issue #232).

`static/style.css` hardcodes --brand-on-primary as #1c1f24 (dark) / #ffffff
(light) -- the text color painted over --brand-primary on the settings
primary button. When a user customizes their brand_primary color via the
theme customization feature, `load_active_theme()` currently emits the
custom brand_primary but never a matching on-color, so the static default
foreground can end up paired with an arbitrary custom brand color that it
does not have sufficient contrast against.

This test file asserts the not-yet-implemented `_on_primary_for()` helper
(api/routes.py) picks a WCAG AA (>= 4.5:1) compliant foreground color for a
given brand color, and that `load_active_theme()` injects a derived
`brand_on_primary` key into the light/dark dicts whenever a custom
brand_primary override is present -- while leaving un-customized themes
(empty overrides) alone so the static CSS defaults still apply.

Expected to FAIL until `_on_primary_for` and the `load_active_theme`
injection described in Issue #232 are implemented.
"""
import json as _json
import os
import sys
import time as _time

import aiosqlite
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import core.database as db_module
from core.database import init_db

# Reused WCAG helper pattern (see tests/test_brand_teal_contrast.py lines 32-54).
from tests.test_brand_teal_contrast import (
    relative_luminance,
    contrast_ratio,
    WCAG_AA_MIN,
)


# ── Fixture: isolated in-memory-style DB (matches tests/test_theme_customization.py) ──

@pytest_asyncio.fixture
async def fresh_db(tmp_path):
    """Run init_db() against a temp file and yield the path. Restores DATABASE_PATH after."""
    db_path = str(tmp_path / "test_theme_on_primary.db")
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = db_path
    try:
        await init_db()
        yield db_path
    finally:
        db_module.DATABASE_PATH = original


# ── Contract 1: _on_primary_for meets WCAG AA against hostile brand colors ──
#
# These brand colors are mid-luminance enough that BOTH existing static
# on-primary tokens fail against them (verified: #7a7f4a scores 3.90 against
# #1c1f24 and 4.23 against #ffffff -- both below the 4.5 WCAG AA minimum).

@pytest.mark.parametrize("brand_hex", ["#7a7f4a", "#767676", "#8a6a3a"])
def test_on_primary_for_meets_wcag_aa_against_hostile_brand_colors(brand_hex):
    from api.routes import _on_primary_for

    on_color = _on_primary_for(brand_hex)
    ratio = contrast_ratio(on_color, brand_hex)
    assert ratio >= WCAG_AA_MIN, (
        f"_on_primary_for({brand_hex!r}) returned {on_color!r} with contrast "
        f"ratio {ratio:.2f} against {brand_hex!r}, below WCAG AA minimum {WCAG_AA_MIN}"
    )


# ── Contract 2: _on_primary_for reproduces the existing hand-picked defaults ──

def test_on_primary_for_reproduces_dark_default_for_light_theme_brand():
    from api.routes import _on_primary_for

    assert _on_primary_for("#14b8a6") == "#1c1f24"


def test_on_primary_for_reproduces_white_default_for_dark_theme_brand():
    from api.routes import _on_primary_for

    assert _on_primary_for("#0e7268") == "#ffffff"


# ── Contract 3: load_active_theme injects brand_on_primary for custom colors ──

@pytest.mark.asyncio
@pytest.mark.unit
async def test_load_active_theme_injects_brand_on_primary_for_custom_colors(fresh_db):
    """When a hostile custom brand_primary is stored for each mode, load_active_theme
    must inject a brand_on_primary key into that mode's dict which meets WCAG AA
    contrast against that mode's own stored brand_primary."""
    from api.routes import load_active_theme, _ensure_default_theme

    await _ensure_default_theme(user_id=1)

    light_brand = "#7a7f4a"
    dark_brand = "#767676"

    now = int(_time.time())
    light_overrides = _json.dumps({"brand_primary": light_brand})
    dark_overrides = _json.dumps({"brand_primary": dark_brand})
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute(
            "UPDATE user_themes SET light_overrides_json=?, dark_overrides_json=? "
            "WHERE user_id=1 AND is_active=1",
            (light_overrides, dark_overrides),
        )
        await db.commit()

    theme = await load_active_theme(user_id=1)

    assert "brand_on_primary" in theme["light"], (
        f"Expected 'brand_on_primary' to be injected into theme['light'] when a "
        f"custom brand_primary ({light_brand!r}) is stored, got keys: "
        f"{list(theme['light'].keys())}"
    )
    assert "brand_on_primary" in theme["dark"], (
        f"Expected 'brand_on_primary' to be injected into theme['dark'] when a "
        f"custom brand_primary ({dark_brand!r}) is stored, got keys: "
        f"{list(theme['dark'].keys())}"
    )

    light_ratio = contrast_ratio(theme["light"]["brand_on_primary"], light_brand)
    assert light_ratio >= WCAG_AA_MIN, (
        f"theme['light']['brand_on_primary'] ({theme['light']['brand_on_primary']!r}) "
        f"has contrast ratio {light_ratio:.2f} against brand_primary ({light_brand!r}), "
        f"below WCAG AA minimum {WCAG_AA_MIN}"
    )

    dark_ratio = contrast_ratio(theme["dark"]["brand_on_primary"], dark_brand)
    assert dark_ratio >= WCAG_AA_MIN, (
        f"theme['dark']['brand_on_primary'] ({theme['dark']['brand_on_primary']!r}) "
        f"has contrast ratio {dark_ratio:.2f} against brand_primary ({dark_brand!r}), "
        f"below WCAG AA minimum {WCAG_AA_MIN}"
    )


# ── Contract 4: no injection for un-customized (empty overrides) themes ──
#
# Regression guard: the static CSS defaults must win when nothing is
# customized, so brand_on_primary must NOT appear when overrides are {}.

@pytest.mark.asyncio
@pytest.mark.unit
async def test_load_active_theme_does_not_inject_brand_on_primary_for_empty_overrides(fresh_db):
    from api.routes import load_active_theme, _ensure_default_theme

    await _ensure_default_theme(user_id=1)

    theme = await load_active_theme(user_id=1)

    assert theme["light"] == {}, (
        f"Expected empty light overrides for un-customized default theme, "
        f"got: {theme['light']!r}"
    )
    assert theme["dark"] == {}, (
        f"Expected empty dark overrides for un-customized default theme, "
        f"got: {theme['dark']!r}"
    )
    assert "brand_on_primary" not in theme["light"], (
        "brand_on_primary must not be injected into theme['light'] when overrides are empty"
    )
    assert "brand_on_primary" not in theme["dark"], (
        "brand_on_primary must not be injected into theme['dark'] when overrides are empty"
    )
