import os
import re
from html.parser import HTMLParser
import pytest

from tests.js_source import read_static_js

TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "dashboard.html"
)

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class RefreshButtonStructureParser(HTMLParser):
    """Walks dashboard.html and tracks element ancestry to verify reload button placement."""

    def __init__(self):
        super().__init__()
        self._stack = []  # Stack of (tag, id, classes) tuples
        self.reload_buttons_in_sidebar_header = []
        self.reload_buttons_in_nav_actions = []
        self.all_reload_buttons = []

    def _get_id(self, attrs):
        for name, value in attrs:
            if name == "id":
                return value or ""
        return ""

    def _get_classes(self, attrs):
        for name, value in attrs:
            if name == "class":
                return value.split() if value else []
        return []

    def _get_onclick(self, attrs):
        for name, value in attrs:
            if name == "onclick":
                return value or ""
        return ""

    def handle_starttag(self, tag, attrs):
        classes = self._get_classes(attrs)
        el_id = self._get_id(attrs)
        onclick = self._get_onclick(attrs)

        # Identify reload button elements by target class, current class, or handler
        is_reload_btn = (
            "panel-reload-btn" in classes
            or "nav-reload-btn" in classes
            or "softRefresh" in onclick
        )

        if is_reload_btn:
            btn_record = {
                "tag": tag,
                "id": el_id,
                "classes": classes,
                "onclick": onclick,
                "ancestors": list(self._stack),
            }
            self.all_reload_buttons.append(btn_record)

            # Check if button is inside .nav-actions
            if any("nav-actions" in anc[2] for anc in self._stack):
                self.reload_buttons_in_nav_actions.append(btn_record)

            # Check if button is inside #navigator's .header-bar
            in_sidebar_header = False
            for idx, anc in enumerate(self._stack):
                # Navigator sidebar element
                if anc[1] == "navigator":
                    # Check for header-bar inside this navigator
                    for inner_anc in self._stack[idx + 1:]:
                        if "header-bar" in inner_anc[2]:
                            in_sidebar_header = True
                            break
                    if in_sidebar_header:
                        break

            if in_sidebar_header:
                self.reload_buttons_in_sidebar_header.append(btn_record)

        if tag not in VOID_TAGS:
            self._stack.append((tag, el_id, classes))

    def handle_endtag(self, tag):
        if not self._stack:
            return
        if tag in VOID_TAGS:
            return
        if self._stack[-1][0] == tag:
            self._stack.pop()
        else:
            # Handle possible mismatched nesting gracefully by popping to nearest matching tag
            for idx in range(len(self._stack) - 1, -1, -1):
                if self._stack[idx][0] == tag:
                    self._stack = self._stack[:idx]
                    break


def _parse_template() -> RefreshButtonStructureParser:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    parser = RefreshButtonStructureParser()
    parser.feed(html)
    return parser


def _read_template() -> str:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _read_js() -> str:
    return read_static_js()


def _extract_soft_refresh_body(js_content: str) -> str:
    """Extracts only the body of the `function softRefresh() { ... }` declaration."""
    match = re.search(
        r"(?:async\s+)?function\s+softRefresh\s*\([^)]*\)\s*\{",
        js_content,
    )
    if not match:
        raise AssertionError(
            "Could not locate the softRefresh function declaration in the static JS sources"
        )

    start_idx = match.end()  # position immediately after opening '{'
    depth = 1
    i = start_idx
    while i < len(js_content) and depth > 0:
        char = js_content[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        i += 1

    if depth != 0:
        raise AssertionError(
            "Unmatched braces while parsing body of window.softRefresh in static/main.js"
        )

    return js_content[start_idx : i - 1]


@pytest.mark.unit
def test_reload_button_descendant_of_sidebar_header_bar():
    """The reload button element must be a descendant of #navigator's .header-bar."""
    parser = _parse_template()
    assert len(parser.reload_buttons_in_sidebar_header) > 0, (
        "Expected the reload button to be a descendant of the header-bar div inside "
        "<div id=\"navigator\" class=\"sidebar\">, but no reload button was found there."
    )


@pytest.mark.unit
def test_reload_button_not_in_nav_actions():
    """The reload button must NOT be a descendant of .nav-actions."""
    parser = _parse_template()
    assert len(parser.reload_buttons_in_nav_actions) == 0, (
        f"Expected no reload button inside .nav-actions, but found {len(parser.reload_buttons_in_nav_actions)}: "
        f"{parser.reload_buttons_in_nav_actions}. The refresh button should be moved to the sidebar header."
    )


@pytest.mark.unit
def test_reload_button_css_class_renamed():
    """CSS class panel-reload-btn must be present and nav-reload-btn must be removed from dashboard.html."""
    html = _read_template()
    assert "panel-reload-btn" in html, (
        "Expected CSS class 'panel-reload-btn' in templates/dashboard.html, "
        "but it was not found."
    )
    assert "nav-reload-btn" not in html, (
        "Found deprecated CSS class 'nav-reload-btn' in templates/dashboard.html. "
        "The class must be renamed to 'panel-reload-btn'."
    )


@pytest.mark.unit
def test_soft_refresh_does_not_mention_load_monitor_charts():
    """In static/main.js, window.softRefresh body must not mention loadMonitorCharts."""
    js_content = _read_js()
    body = _extract_soft_refresh_body(js_content)
    assert "loadMonitorCharts" not in body, (
        "Expected window.softRefresh body to NOT mention 'loadMonitorCharts', "
        f"but it was found in the function body:\n{body}"
    )
