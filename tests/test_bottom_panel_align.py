import pytest
"""Tests for bottom panel sidebar alignment and expand toggle (Issue #87).

Verifies:
- #bottom-panel-expand-btn exists in the bottom panel header, on the LEFT side
- #navigator is a direct child of .app-container (not inside .workspace-row)
- CSS grid positions the bottom panel aligned with the editor by default
- .is-expanded spans both grid columns (full-width)
- Navigator spans both grid rows by default and retracts when panel is expanded
- CSS ::after icon flips based on .is-expanded
- JS toggleBottomPanelExpand function exists and toggles body.bottom-panel-expanded
- localStorage key qm-bottom-panel-expanded is persisted and restored
"""
import os
from html.parser import HTMLParser

from tests.css_source import read_static_css
from tests.js_source import read_static_js

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")


# ── HTML structure ────────────────────────────────────────────────────────────

class LayoutParser(HTMLParser):
    """Parses dashboard.html to verify structural placement of key elements."""

    def __init__(self):
        super().__init__()
        self._stack = []           # (tag, id, classes) tuples
        self._app_container_depth = None

        # Results
        self.expand_btn_found = False
        self.expand_btn_in_header = False
        self.expand_btn_in_header_actions = False  # expand btn in right-edge .bottom-panel-header-actions
        self.navigator_in_app_container = False   # navigator must be direct child of .app-container
        self.navigator_in_workspace_row = False   # navigator must NOT be inside .workspace-row

        self._in_header = False
        self._header_depth = None
        self._in_workspace_row = False
        self._workspace_row_depth = None
        self._in_header_actions = False
        self._header_children_ids = []  # ordered list of ids of direct children of header

    def _get_id(self, attrs):
        return dict(attrs).get("id", "")

    def _get_classes(self, attrs):
        cls = dict(attrs).get("class", "")
        return cls.split() if cls else []

    def handle_starttag(self, tag, attrs):
        depth = len(self._stack) + 1
        classes = self._get_classes(attrs)
        el_id = self._get_id(attrs)
        self._stack.append((tag, el_id, classes))

        # Track .app-container depth
        if "app-container" in classes and self._app_container_depth is None:
            self._app_container_depth = depth

        # Track .workspace-row
        if "workspace-row" in classes:
            self._in_workspace_row = True
            self._workspace_row_depth = depth

        # Track .bottom-panel-header
        if "bottom-panel-header" in classes:
            self._in_header = True
            self._header_depth = depth

        # Record direct children of bottom-panel-header (depth = header_depth + 1).
        # Two-row layout: Row 1 is .bottom-panel-header-row1; treat it and
        # .bottom-panel-tabs-group as the tabs container so the test works
        # regardless of nesting depth.
        if self._header_depth and depth == self._header_depth + 1:
            effective_classes = classes[:]
            if "bottom-panel-tabs-group" in classes or "bottom-panel-header-row1" in classes:
                effective_classes = effective_classes + ["bottom-panel-tabs"]
            self._header_children_ids.append((el_id, effective_classes))

        # Track .bottom-panel-header-actions (right-edge button group)
        if "bottom-panel-header-actions" in classes:
            self._in_header_actions = True

        # Expand button
        if el_id == "bottom-panel-expand-btn":
            self.expand_btn_found = True
            if self._in_header:
                self.expand_btn_in_header = True
            if self._in_header_actions:
                self.expand_btn_in_header_actions = True

        # Navigator placement
        if el_id == "navigator":
            # Direct child of .app-container: depth == app_container_depth + 1
            if self._app_container_depth and depth == self._app_container_depth + 1:
                self.navigator_in_app_container = True
            if self._in_workspace_row:
                self.navigator_in_workspace_row = True

    def handle_endtag(self, tag):
        if not self._stack:
            return
        depth = len(self._stack)
        _, _, classes = self._stack[-1]

        if self._workspace_row_depth and depth == self._workspace_row_depth:
            self._in_workspace_row = False
            self._workspace_row_depth = None

        if self._in_header_actions and "bottom-panel-header-actions" in classes:
            self._in_header_actions = False

        if self._header_depth and depth == self._header_depth:
            self._in_header = False
            self._header_depth = None

        self._stack.pop()


def _parse_html():
    with open(TEMPLATE_PATH) as f:
        html = f.read()
    p = LayoutParser()
    p.feed(html)
    return p


@pytest.mark.unit
def test_expand_button_exists():
    """dashboard.html must have a button with id='bottom-panel-expand-btn'."""
    p = _parse_html()
    assert p.expand_btn_found, (
        "Expected <button id=\"bottom-panel-expand-btn\"> in dashboard.html — "
        "the expand-left toggle must be present in the bottom panel header."
    )


@pytest.mark.unit
def test_expand_button_in_header():
    """The expand button must be inside .bottom-panel-header."""
    p = _parse_html()
    assert p.expand_btn_in_header, (
        "Expected #bottom-panel-expand-btn to be a descendant of .bottom-panel-header."
    )


@pytest.mark.unit
def test_expand_button_before_tabs():
    """Expand button must be in .bottom-panel-header-actions (right-edge of Row 1)."""
    p = _parse_html()
    assert p.expand_btn_in_header_actions, (
        "Expected #bottom-panel-expand-btn to be inside .bottom-panel-header-actions. "
        "The two-row header redesign (issue #121) moved it to the right-edge actions group."
    )


@pytest.mark.unit
def test_navigator_is_direct_child_of_app_container():
    """#navigator must be a direct child of .app-container, not nested in .workspace-row."""
    p = _parse_html()
    assert p.navigator_in_app_container, (
        "Expected #navigator to be a direct child of .app-container so it can span "
        "both grid rows (workspace row + bottom panel row)."
    )


@pytest.mark.unit
def test_navigator_not_inside_workspace_row():
    """#navigator must NOT be inside .workspace-row (it has been promoted to .app-container)."""
    p = _parse_html()
    assert not p.navigator_in_workspace_row, (
        "#navigator should not be inside .workspace-row — it must be a sibling of "
        ".workspace-row in .app-container so CSS grid can span it across both rows."
    )


# ── CSS rules ─────────────────────────────────────────────────────────────────

def _read_css():
    return read_static_css()


@pytest.mark.unit
def test_app_container_uses_grid_in_containers_view():
    """body.view-containers .app-container must use CSS grid layout."""
    css = _read_css()
    assert "view-containers" in css, (
        "Expected 'body.view-containers .app-container { display: grid; ... }' in style.css "
        "so the sidebar and workspace column can be laid out independently."
    )
    assert "display: grid" in css, (
        "Expected 'body.view-containers .app-container { display: grid; ... }' in style.css "
        "so the sidebar and workspace column can be laid out independently."
    )


@pytest.mark.unit
def test_grid_has_sidebar_column():
    """The CSS grid must use var(--sidebar-width) to size the navigator column."""
    css = _read_css()
    assert "grid-template-columns" in css, (
        "Expected grid-template-columns to include var(--sidebar-width) so the navigator "
        "column tracks the resizable sidebar width."
    )
    assert "var(--sidebar-width)" in css, (
        "Expected grid-template-columns to include var(--sidebar-width) so the navigator "
        "column tracks the resizable sidebar width."
    )


@pytest.mark.unit
def test_navigator_spans_both_grid_rows():
    """#navigator must use grid-row: 1 / 3 to extend alongside the bottom panel."""
    css = _read_css()
    assert "grid-row: 1 / 3" in css or "grid-row: 1/3" in css, (
        "Expected '#navigator { grid-row: 1 / 3; }' so the sidebar extends downward "
        "to fill the space alongside the bottom panel."
    )


@pytest.mark.unit
def test_is_expanded_spans_both_columns():
    """#bottom-panel.is-expanded must span both grid columns for full-width layout."""
    css = _read_css()
    assert "is-expanded" in css, (
        "Expected a .is-expanded CSS rule for #bottom-panel."
    )
    assert "1 / 3" in css or "1/3" in css, (
        "Expected grid-column: 1 / 3 in the is-expanded rule to span full width."
    )


@pytest.mark.unit
def test_body_class_retracts_navigator_when_expanded():
    """body.bottom-panel-expanded must set navigator back to grid-row: 1."""
    css = _read_css()
    assert "bottom-panel-expanded" in css, (
        "Expected a 'body.bottom-panel-expanded #navigator' rule to retract the "
        "navigator to row 1 when the panel is expanded to full width."
    )


@pytest.mark.unit
def test_expand_btn_icon_flips_on_expanded():
    """CSS ::after on #bottom-panel-expand-btn must flip icon when .is-expanded."""
    css = _read_css()
    assert "bottom-panel-expand-btn::after" in css, (
        "Expected #bottom-panel-expand-btn::after CSS rule for the expand icon."
    )
    assert "is-expanded" in css, (
        "Expected an .is-expanded scoped rule for #bottom-panel-expand-btn::after "
        "to flip the icon direction."
    )
    assert "bottom-panel-expand-btn" in css, (
        "Expected an .is-expanded scoped rule for #bottom-panel-expand-btn::after "
        "to flip the icon direction."
    )


# ── JS behaviour ─────────────────────────────────────────────────────────────

def _read_js():
    return read_static_js()


@pytest.mark.unit
def test_toggle_expand_function_exists():
    """main.js must define window.toggleBottomPanelExpand."""
    js = _read_js()
    assert "toggleBottomPanelExpand" in js, (
        "Expected window.toggleBottomPanelExpand to be defined in main.js."
    )


@pytest.mark.unit
def test_toggle_expand_toggles_body_class():
    """toggleBottomPanelExpand must toggle body.bottom-panel-expanded."""
    js = _read_js()
    assert "bottom-panel-expanded" in js, (
        "Expected 'bottom-panel-expanded' body class to be toggled in main.js so the "
        "CSS can retract the navigator when the panel is expanded."
    )


@pytest.mark.unit
def test_expand_state_persisted_to_localstorage():
    """toggleBottomPanelExpand must write to localStorage key qm-bottom-panel-expanded."""
    js = _read_js()
    assert "qm-bottom-panel-expanded" in js, (
        "Expected 'qm-bottom-panel-expanded' localStorage key in main.js."
    )


@pytest.mark.unit
def test_expand_state_restored_on_load():
    """restorePanelWidths must read qm-bottom-panel-expanded and apply is-expanded class."""
    js = _read_js()
    assert "qm-bottom-panel-expanded" in js, (
        "Expected qm-bottom-panel-expanded to be read during panel width restore."
    )
    assert "is-expanded" in js, (
        "Expected is-expanded class to be toggled based on localStorage in main.js."
    )
