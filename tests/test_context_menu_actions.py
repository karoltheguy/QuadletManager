import pytest
"""Tests for context menu actions: Edit, Start, Stop (issue #71).

Verifies that static/main.js contains the correct patterns for the new
context menu items and that the unit name derivation matches what the
backend expects (stem + '.service').
"""
import os
import re

MAIN_JS = os.path.join(os.path.dirname(__file__), '..', 'static', 'main.js')


def _read_js():
    with open(MAIN_JS, 'r') as f:
        return f.read()


# =============================================================================
# Context menu item presence
# =============================================================================


@pytest.mark.unit
def test_context_menu_has_edit_item():
    js = _read_js()
    assert "textContent = 'Edit'" in js, "Edit menu item must be present"


@pytest.mark.unit
def test_context_menu_has_start_item():
    js = _read_js()
    assert "textContent = 'Start'" in js, "Start menu item must be present"


@pytest.mark.unit
def test_context_menu_has_stop_item():
    js = _read_js()
    assert "textContent = 'Stop'" in js, "Stop menu item must be present"


@pytest.mark.unit
def test_context_menu_has_delete_item():
    js = _read_js()
    assert "textContent = 'Delete'" in js, "Delete menu item must still be present"


# =============================================================================
# Unit name derivation: stem + '.service'
# =============================================================================


@pytest.mark.unit
def test_unit_name_derived_from_stem():
    """The JS must derive unitName as stem + '.service', matching api/routes.py:217."""
    js = _read_js()
    assert "unitName = stem + '.service'" in js, \
        "unitName must be derived as stem + '.service'"


@pytest.mark.unit
def test_stem_strips_extension():
    """The stem regex must strip the last extension from the filename."""
    js = _read_js()
    assert "fileName.replace(/\\.[^.]+$/, '')" in js, \
        "stem must strip last extension via /\\.[^.]+$/ regex"


# =============================================================================
# Edit action: loads file into editor pane and switches tab
# =============================================================================


@pytest.mark.unit
def test_edit_action_targets_editor_pane():
    js = _read_js()
    assert "target: '#editor-pane'" in js, \
        "Edit action must target #editor-pane for HTMX swap"


@pytest.mark.unit
def test_edit_action_uses_outerhtml_swap():
    js = _read_js()
    assert "swap: 'outerHTML'" in js, \
        "Edit action must use outerHTML swap to replace editor pane"


@pytest.mark.unit
def test_edit_action_switches_to_editor_tab():
    js = _read_js()
    # The editor lives inside the containers tab; edit action must switch to it
    assert "switchTab('containers')" in js, \
        "Edit action must call switchTab('containers') to reveal the editor pane"


@pytest.mark.unit
def test_edit_action_calls_api_file_endpoint():
    js = _read_js()
    assert "'/api/file/' + serverId" in js, \
        "Edit action must call /api/file/{serverId}"


# =============================================================================
# Start/Stop actions: use correct API endpoint with swap:none
# =============================================================================


@pytest.mark.unit
def test_start_action_uses_systemctl_endpoint():
    js = _read_js()
    assert "action=start" in js, \
        "Start action must POST with action=start to systemctl endpoint"


@pytest.mark.unit
def test_stop_action_uses_systemctl_endpoint():
    js = _read_js()
    assert "action=stop" in js, \
        "Stop action must POST with action=stop to systemctl endpoint"


@pytest.mark.unit
def test_start_stop_use_swap_none():
    """swap:'none' ensures htmx:beforeRequest fires (for notifications) without
    needing a DOM target — critical when the user is not on the editor tab."""
    js = _read_js()
    assert js.count("swap: 'none'") >= 2, \
        "Both Start and Stop must use swap: 'none'"


# =============================================================================
# Menu item order: Edit, Start, Stop, Delete
# =============================================================================


@pytest.mark.unit
def test_menu_item_order():
    """Edit must come before Start, Start before Stop, Stop before Delete."""
    js = _read_js()
    edit_pos = js.find("textContent = 'Edit'")
    start_pos = js.find("textContent = 'Start'")
    stop_pos = js.find("textContent = 'Stop'")
    delete_pos = js.find("textContent = 'Delete'")
    assert edit_pos < start_pos < stop_pos < delete_pos, \
        "Menu items must appear in order: Edit, Start, Stop, Delete"
