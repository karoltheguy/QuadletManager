import pytest
"""
Tests for design-lint fixes in static/style.css (Issue #226).

Covers:
- .inspector-panel no longer transitions `width`/`flex` (expensive layout
  properties should not be animated via `transition`).
- .theme-card.active drops the `border-left` accent in favor of an inset
  brand-colored box-shadow ring.
- .container-activity-log .activity-item drops its `border-left` accent.
"""
import re

from tests.css_source import read_static_css


def _css():
    return read_static_css()


def _extract_rule_block(css, selector_regex):
    """Extract the declaration block `{ ... }` for the first rule whose
    selector matches selector_regex. Returns the block body (without braces)
    or None if not found."""
    m = re.search(selector_regex + r"\s*\{", css)
    if not m:
        return None
    start = m.end()
    end = css.index("}", start)
    return css[start:end]


class TestInspectorPanelNoLayoutTransition:
    def setup_method(self):
        self.css = _css()
        self.block = _extract_rule_block(self.css, r"\.inspector-panel")

    @pytest.mark.unit
    def test_inspector_panel_does_not_transition_width_or_flex(self):
        assert self.block is not None, ".inspector-panel rule block not found"
        assert re.search(r"transition:[^;]*\b(width|flex)\b", self.block) is None, (
            ".inspector-panel should not transition 'width' or 'flex'"
        )


class TestThemeCardActiveUsesInsetRingNotBorderLeft:
    def setup_method(self):
        self.css = _css()
        self.block = _extract_rule_block(self.css, r"\.theme-card\.active")

    @pytest.mark.unit
    def test_theme_card_active_has_no_border_left(self):
        assert self.block is not None, ".theme-card.active rule block not found"
        assert "border-left" not in self.block, (
            ".theme-card.active should not use 'border-left'"
        )

    @pytest.mark.unit
    def test_theme_card_active_has_inset_brand_ring(self):
        assert self.block is not None, ".theme-card.active rule block not found"
        assert re.search(
            r"inset 0 0 0 1px var\(--brand-primary\)", self.block
        ) is not None, (
            ".theme-card.active should include an inset brand-primary ring "
            "in its box-shadow"
        )


class TestActivityItemNoBorderLeft:
    def setup_method(self):
        self.css = _css()
        self.block = _extract_rule_block(
            self.css, r"\.container-activity-log \.activity-item"
        )

    @pytest.mark.unit
    def test_activity_item_has_no_border_left(self):
        assert self.block is not None, (
            ".container-activity-log .activity-item rule block not found"
        )
        assert "border-left" not in self.block, (
            ".container-activity-log .activity-item should not use "
            "'border-left'"
        )
