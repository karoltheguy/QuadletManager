import pytest
"""
Tests for defining the `.border-b` utility class (Issue #263).

`static/main.js` applies a `border-b` class in `renderContainerRow`
(`tr.className = 'border-b'`), but `static/style.css` never defines a
`.border-b` rule. The class is dead; the rendered table has no row
separators.

The fix defines `.border-b` in the utilities block of style.css
(`border-bottom: 1px solid var(--border-color)`), while carving out
scoped exceptions so the Monitor stats table keeps its existing behavior:

- The sticky header (`thead th`) keeps its own `box-shadow` separator
  (a pre-existing rule, unaffected by this fix). The header row does not
  carry `border-b` at all: the table is `border-collapse: collapse`, so a
  row-level border there would both double the box-shadow line and scroll
  away from the stuck cells.
- The last body row (`tbody tr:last-child`) must suppress the new
  `border-bottom` (set it to `none`), so it does not double against the
  `.stats-table-wrapper` 1px border.

Covers:
- .border-b is defined in the utilities block with the expected declaration
- the Monitor sticky header's box-shadow separator regression guard
- the last body row of the Monitor stats table carries no separator
- main.js applies border-b to body rows via renderContainerRow
- the Monitor stats table header row deliberately does not carry border-b
"""
import os
import re

from tests.js_source import read_static_js

CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")


def _css():
    with open(CSS_PATH, encoding="utf-8") as f:
        return f.read()


def _js():
    return read_static_js()


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


class TestBorderBUtilityDefined:
    def setup_method(self):
        self.css = _css()
        # Line-anchored so this cannot accidentally bind to the scoped
        # override `#monitoring-stats-table thead tr.border-b`.
        self.block = _extract_rule_block(self.css, r"(?m)^\s*\.border-b")

    @pytest.mark.unit
    def test_border_b_utility_block_exists(self):
        assert self.block is not None, (
            "Expected a `.border-b` rule in the utilities block of "
            "style.css, but none was found"
        )

    @pytest.mark.unit
    def test_border_b_declares_expected_border_bottom(self):
        assert self.block is not None
        assert "border-bottom" in self.block, (
            "Expected .border-b to declare `border-bottom`"
        )
        assert "1px" in self.block, (
            "Expected .border-b's border-bottom to use `1px`"
        )
        assert "solid" in self.block, (
            "Expected .border-b's border-bottom to use `solid`"
        )
        assert "var(--border-color)" in self.block, (
            "Expected .border-b's border-bottom to use `var(--border-color)`"
        )


class TestMonitoringStickyHeaderKeepsBoxShadowSeparator:
    """Regression guard on an existing rule; must pass both before and
    after the .border-b fix."""

    def setup_method(self):
        self.css = _css()
        self.block = _extract_rule_block(
            self.css,
            r"\.monitoring-content\s+#monitoring-stats-table\s+thead\s+th",
        )

    @pytest.mark.unit
    def test_sticky_header_block_exists(self):
        assert self.block is not None, (
            "Expected a rule for "
            "`.monitoring-content #monitoring-stats-table thead th`"
        )

    @pytest.mark.unit
    def test_sticky_header_has_inset_box_shadow(self):
        assert self.block is not None
        assert re.search(r"box-shadow\s*:[^;]*inset\s+0\s+-1px\s+0", self.block), (
            "Expected the Monitor sticky header th to keep its "
            "`box-shadow: inset 0 -1px 0 ...` separator"
        )


class TestMonitoringLastBodyRowHasNoSeparator:
    def setup_method(self):
        self.css = _css()
        self.block = _extract_rule_block(
            self.css,
            r"[^{}]*#monitoring-stats-table\s+tbody\s+tr:last-child[^{}]*",
        )

    @pytest.mark.unit
    def test_last_body_row_rule_exists(self):
        assert self.block is not None, (
            "Expected a rule whose selector contains "
            "`#monitoring-stats-table tbody tr:last-child`"
        )

    @pytest.mark.unit
    def test_last_body_row_border_bottom_is_none(self):
        assert self.block is not None
        assert re.search(r"border-bottom\s*:\s*none", self.block), (
            "Expected `#monitoring-stats-table tbody tr:last-child` to "
            "declare `border-bottom: none`, so it does not double against "
            "the `.stats-table-wrapper` 1px border"
        )


class TestMainJsAppliesBorderBOnlyToBodyRows:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_render_container_row_applies_border_b(self):
        assert "tr.className = 'border-b'" in self.js, (
            "Expected renderContainerRow to still set "
            "tr.className = 'border-b'"
        )

    @pytest.mark.unit
    def test_render_container_stats_table_header_omits_border_b(self):
        assert re.search(
            r"headerRow\.className\s*=\s*'[^']*text-muted[^']*'", self.js
        ), "Expected headerRow.className to contain 'text-muted'"
        assert not re.search(
            r"headerRow\.className\s*=\s*'[^']*border-b[^']*'", self.js
        ), "Expected headerRow.className to NOT contain 'border-b'"
