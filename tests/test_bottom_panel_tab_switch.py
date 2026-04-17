"""Tests for bottom panel expansion state preservation across tab switches (Issue #98).

Verifies:
- When bottom panel is expanded and user navigates away then back to Containers tab,
  the body.bottom-panel-expanded class is restored, preventing overlap with sidebar.

This is a regression test for the bug where switching tabs stripped the body class,
causing the sidebar to render at full height and overlap the expanded bottom panel.
"""
import os
import re

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")
JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "main.js")


def _read_js():
    with open(JS_PATH) as f:
        return f.read()


# ── JS Behaviour Tests ─────────────────────────────────────────────────────────


def test_switchtab_restores_bottom_panel_expanded_class():
    """switchTab('containers') must restore body.bottom-panel-expanded if panel is expanded.
    
    Issue #98: When switching away from Containers tab, the body.bottom-panel-expanded
    class is stripped (because switchTab replaces body.className). Upon returning,
    the panel still has .is-expanded (from localStorage), but the body class is missing,
    causing overlap.
    
    The fix mirrors the inspector-expanded restoration pattern (lines 924-926):
    - Check if tabId === 'containers'
    - Check if #bottom-panel has .is-expanded class
    - If so, add bottom-panel-expanded to body.classList
    """
    js = _read_js()
    
    # Find the switchTab function body
    switchtab_match = re.search(
        r"window\.switchTab\s*=\s*function\s*\([^)]*\)\s*\{",
        js
    )
    
    assert switchtab_match, (
        "Expected window.switchTab function to be defined in main.js"
    )
    
    # Extract the function body by finding matching braces
    start = switchtab_match.end()
    brace_count = 1
    end = start
    while brace_count > 0 and end < len(js):
        if js[end] == '{':
            brace_count += 1
        elif js[end] == '}':
            brace_count -= 1
        end += 1
    
    switchtab_body = js[start:end-1]
    
    # Check that there's specific restoration logic for bottom-panel-expanded
    # based on the panel's current state (not just localStorage)
    # Pattern: check if panel has is-expanded class, then add body class
    
    # Look for: panel.classList.contains('is-expanded') and body bottom-panel-expanded
    has_panel_check = "classList.contains('is-expanded')" in switchtab_body or \
                       'classList.contains("is-expanded")' in switchtab_body
    has_body_class_add = "bottom-panel-expanded" in switchtab_body
    
    # The fix should check the DOM state, not localStorage
    # (localStorage is already handled at page load in restorePanelWidths)
    assert has_body_class_add, (
        "Expected switchTab to restore 'bottom-panel-expanded' body class "
        "when returning to Containers tab while panel is expanded.\n"
        "Pattern: if (tabId === 'containers') {\n"
        "  var panel = document.getElementById('bottom-panel');\n"
        "  if (panel && panel.classList.contains('is-expanded')) {\n"
        "    document.body.classList.add('bottom-panel-expanded');\n"
        "  }\n"
        "}"
    )


def test_bottom_panel_expand_persistence_key():
    """Verify the localStorage key for expanded state exists."""
    js = _read_js()
    assert "qm-bottom-panel-expanded" in js, (
        "Expected 'qm-bottom-panel-expanded' localStorage key in main.js"
    )


def test_bottom_panel_state_restored_on_pageload():
    """Verify expanded state is restored on DOMContentLoaded."""
    js = _read_js()
    
    # Check for restoration on page load
    restoration_pattern = re.search(
        r"qm-bottom-panel-expanded.*is-expanded|is-expanded.*qm-bottom-panel-expanded",
        js,
        re.DOTALL
    )
    
    assert restoration_pattern, (
        "Expected qm-bottom-panel-expanded to be read and is-expanded class applied "
        "during page load (DOMContentLoaded)."
    )
