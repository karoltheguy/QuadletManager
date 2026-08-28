import pytest
"""
Tests for Servers-table actions cell button spacing (Issue #227).

Covers:
- .settings-table td.actions-col should use display:flex + gap so its
  action buttons have breathing room instead of being crammed together.
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


@pytest.mark.unit
def test_servers_actions_cell_has_flex_gap():
    """Issue #227: the Servers-table actions cell should give its buttons
    breathing room via display:flex + gap."""
    css = _css()
    block = _extract_rule_block(css, r"\.settings-table td\.actions-col")
    assert block is not None, "actions-col td rule not found"
    assert "display: flex" in block or "display:flex" in block
    assert "gap" in block
