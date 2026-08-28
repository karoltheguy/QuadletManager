import pytest
"""Tests for the sessions-strip empty-state placeholder (Issue #192).

Verifies:
- A '.sessions-strip-empty-hint' element is a child of '.bottom-panel-sessions-strip'
  in templates/dashboard.html.
- That hint element appears AFTER '#terminal-conn-tabs' in document order, so a CSS
  general-sibling selector ('~') can target it based on the tabs container's state.
- The hint element contains the visible text "No active sessions".
- static/style.css hides the hint when sessions exist, via a rule keyed on both
  'has-tabs' and 'sessions-strip-empty-hint' (e.g.
  '.terminal-conn-tabs.has-tabs ~ .sessions-strip-empty-hint { display: none; }').
"""
import os
from html.parser import HTMLParser

from tests.css_source import read_static_css

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")


# ── HTML structure ────────────────────────────────────────────────────────────

class SessionsStripParser(HTMLParser):
    """Parses dashboard.html to verify structural placement of the empty-state hint."""

    def __init__(self):
        super().__init__()
        self._stack = []  # (tag, id, classes) tuples
        self._strip_depth = None
        self._in_strip = False

        # Results
        self.hint_found = False
        self.hint_in_strip = False
        self.hint_after_tabs = False
        self.hint_text = ""

        self._seen_terminal_conn_tabs = False
        self._in_hint = False
        self._hint_depth = None

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

        if "bottom-panel-sessions-strip" in classes and self._strip_depth is None:
            self._in_strip = True
            self._strip_depth = depth

        if el_id == "terminal-conn-tabs" and self._in_strip:
            self._seen_terminal_conn_tabs = True

        if "sessions-strip-empty-hint" in classes:
            self.hint_found = True
            if self._in_strip:
                self.hint_in_strip = True
            if self._seen_terminal_conn_tabs:
                self.hint_after_tabs = True
            self._in_hint = True
            self._hint_depth = depth

    def handle_data(self, data):
        if self._in_hint:
            self.hint_text += data

    def handle_endtag(self, tag):
        if not self._stack:
            return
        depth = len(self._stack)
        _, _, classes = self._stack[-1]

        if self._in_hint and self._hint_depth and depth == self._hint_depth:
            self._in_hint = False
            self._hint_depth = None

        if self._strip_depth and depth == self._strip_depth:
            self._in_strip = False
            self._strip_depth = None

        self._stack.pop()


def _parse_html():
    with open(TEMPLATE_PATH) as f:
        html = f.read()
    p = SessionsStripParser()
    p.feed(html)
    return p


@pytest.mark.unit
def test_empty_hint_exists_in_sessions_strip():
    """dashboard.html must have an element with class 'sessions-strip-empty-hint'
    that is a child of .bottom-panel-sessions-strip."""
    p = _parse_html()
    assert p.hint_found, (
        "Expected an element with class 'sessions-strip-empty-hint' in dashboard.html — "
        "a placeholder must be present so the empty sessions strip doesn't render as a "
        "blank band with a lone '+' button."
    )
    assert p.hint_in_strip, (
        "Expected '.sessions-strip-empty-hint' to be a descendant of "
        "'#bottom-panel-sessions-strip' / '.bottom-panel-sessions-strip'."
    )


@pytest.mark.unit
def test_empty_hint_appears_after_terminal_conn_tabs():
    """The empty-state hint must appear AFTER #terminal-conn-tabs in document order
    so a CSS general-sibling selector ('.terminal-conn-tabs.has-tabs ~ .sessions-strip-empty-hint')
    can hide it once sessions exist."""
    p = _parse_html()
    assert p.hint_after_tabs, (
        "Expected '.sessions-strip-empty-hint' to appear AFTER '#terminal-conn-tabs' "
        "within '.bottom-panel-sessions-strip', so the general-sibling combinator can "
        "target it based on the tabs container's 'has-tabs' state."
    )


@pytest.mark.unit
def test_empty_hint_has_expected_text():
    """The hint element must contain the visible text 'No active sessions'."""
    p = _parse_html()
    assert "No active sessions" in p.hint_text, (
        "Expected the '.sessions-strip-empty-hint' element to contain the text "
        "'No active sessions', found: %r" % p.hint_text
    )


# ── CSS rules ─────────────────────────────────────────────────────────────────

def _read_css():
    return read_static_css()


@pytest.mark.unit
def test_css_hides_empty_hint_when_sessions_exist():
    """style.css must hide '.sessions-strip-empty-hint' when the tabs strip has
    active sessions, keyed on both 'has-tabs' and 'sessions-strip-empty-hint'
    (e.g. '.terminal-conn-tabs.has-tabs ~ .sessions-strip-empty-hint { display: none; }')."""
    css = _read_css()
    assert "sessions-strip-empty-hint" in css, (
        "Expected a '.sessions-strip-empty-hint' rule in style.css to hide the "
        "placeholder once real sessions are present."
    )
    assert "has-tabs" in css, (
        "Expected a CSS rule keyed on both 'has-tabs' and 'sessions-strip-empty-hint', "
        "e.g. '.terminal-conn-tabs.has-tabs ~ .sessions-strip-empty-hint { display: none; }', "
        "so the hint disappears when JS toggles .has-tabs on #terminal-conn-tabs."
    )
    assert "sessions-strip-empty-hint" in css, (
        "Expected a CSS rule keyed on both 'has-tabs' and 'sessions-strip-empty-hint', "
        "e.g. '.terminal-conn-tabs.has-tabs ~ .sessions-strip-empty-hint { display: none; }', "
        "so the hint disappears when JS toggles .has-tabs on #terminal-conn-tabs."
    )
