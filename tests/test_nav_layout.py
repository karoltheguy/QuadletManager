import pytest
"""
Tests for nav layout restructure (Issue #66):
- Primary nav tabs (.nav-tabs) must be a distinct container
- Utility controls (.nav-actions) must be a distinct container
- Theme toggle must be in .nav-actions, not .nav-tabs or a bare child of .top-nav
- Nav buttons (Overview, Monitor, Containers, Settings) must be in .nav-tabs
- .nav-links must not be used (replaced by the two new containers)
"""
import os
import sys
from html.parser import HTMLParser

TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "dashboard.html"
)


class NavStructureParser(HTMLParser):
    """Walks dashboard.html and records which elements appear inside which containers."""

    def __init__(self):
        super().__init__()
        self._stack = []          # stack of (tag, classes) tuples
        self.nav_tabs_children = []    # classes of direct button/div children of .nav-tabs
        self.nav_actions_children = [] # classes of direct button/div children of .nav-actions
        self.nav_links_found = False
        self.nav_tabs_found = False
        self.nav_actions_found = False
        self._nav_tabs_depth = None
        self._nav_actions_depth = None

    def _classes(self, attrs):
        for name, value in attrs:
            if name == "class":
                return value.split() if value else []
        return []

    def handle_starttag(self, tag, attrs):
        classes = self._classes(attrs)
        self._stack.append((tag, classes))
        depth = len(self._stack)

        if "nav-links" in classes:
            self.nav_links_found = True

        if "nav-tabs" in classes:
            self.nav_tabs_found = True
            self._nav_tabs_depth = depth

        if "nav-actions" in classes:
            self.nav_actions_found = True
            self._nav_actions_depth = depth

        # Record immediate children of nav-tabs (depth = nav_tabs_depth + 1)
        if self._nav_tabs_depth and depth == self._nav_tabs_depth + 1:
            self.nav_tabs_children.append(classes)

        # Record immediate children of nav-actions (depth = nav_actions_depth + 1)
        if self._nav_actions_depth and depth == self._nav_actions_depth + 1:
            self.nav_actions_children.append(classes)

    def handle_endtag(self, tag):
        if self._stack:
            closed_tag, closed_classes = self._stack[-1]
            depth = len(self._stack)

            if self._nav_tabs_depth and depth == self._nav_tabs_depth:
                # We're closing .nav-tabs itself
                if "nav-tabs" in closed_classes:
                    self._nav_tabs_depth = None

            if self._nav_actions_depth and depth == self._nav_actions_depth:
                if "nav-actions" in closed_classes:
                    self._nav_actions_depth = None

            self._stack.pop()


def _parse_template():
    with open(TEMPLATE_PATH, "r") as f:
        html = f.read()
    parser = NavStructureParser()
    parser.feed(html)
    return parser


@pytest.mark.unit
def test_nav_tabs_container_exists():
    """dashboard.html must have a .nav-tabs container for primary navigation."""
    p = _parse_template()
    assert p.nav_tabs_found, (
        "Expected a <div class=\"nav-tabs\"> (or similar) in dashboard.html — "
        "primary nav tabs must be in their own container, not mixed with utility controls."
    )


@pytest.mark.unit
def test_nav_actions_container_exists():
    """dashboard.html must have a .nav-actions container for utility controls."""
    p = _parse_template()
    assert p.nav_actions_found, (
        "Expected a <div class=\"nav-actions\"> in dashboard.html — "
        "theme toggle and profile must be grouped separately from nav tabs."
    )


@pytest.mark.unit
def test_nav_links_not_used():
    """.nav-links must be removed — replaced by .nav-tabs + .nav-actions."""
    p = _parse_template()
    assert not p.nav_links_found, (
        "Found .nav-links in dashboard.html — this should be replaced by "
        ".nav-tabs and .nav-actions to separate navigation from utility controls."
    )


@pytest.mark.unit
def test_nav_tabs_contains_nav_items():
    """The .nav-tabs container must contain elements with class nav-item."""
    p = _parse_template()
    assert p.nav_tabs_found, "nav-tabs container not found (see test_nav_tabs_container_exists)"
    has_nav_item = any("nav-item" in classes for classes in p.nav_tabs_children)
    assert has_nav_item, (
        f"Expected .nav-tabs to contain .nav-item buttons. "
        f"Found children with classes: {p.nav_tabs_children}"
    )


@pytest.mark.unit
def test_theme_toggle_in_nav_actions():
    """The theme toggle must be inside .nav-actions, not loose in .nav-tabs."""
    p = _parse_template()
    assert p.nav_actions_found, "nav-actions container not found"
    has_theme_toggle = any("theme-toggle" in classes for classes in p.nav_actions_children)
    assert has_theme_toggle, (
        f"Expected .theme-toggle to be a direct child of .nav-actions. "
        f"Found nav-actions children: {p.nav_actions_children}"
    )
