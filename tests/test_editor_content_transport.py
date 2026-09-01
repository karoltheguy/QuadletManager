"""
Tests for passing file content to the editor via the DOM instead of JS template literals
(Issue #467).

These assert wiring that does not exist yet -- templates/partials/editor_pane.html
currently interpolates safe_content into a JavaScript template literal, and api/routes.py
still computes safe_content with manual backtick escaping. This is the RED phase of a
TDD cycle: all tests below are expected to fail until DOM transport is implemented.
"""
import os
import pytest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
EDITOR_PANE_HTML_PATH = os.path.join(BASE_DIR, "templates", "partials", "editor_pane.html")
ROUTES_PY_PATH = os.path.join(BASE_DIR, "api", "routes.py")


def _editor_pane_html():
    with open(EDITOR_PANE_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _routes_py():
    with open(ROUTES_PY_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.mark.unit
def test_hidden_content_textarea_carries_the_file_content():
    """Verify that #hidden-content textarea contains exact {{ content }} without whitespace."""
    html = _editor_pane_html()
    assert ">{{ content }}</textarea>" in html, (
        "Expected templates/partials/editor_pane.html to contain a <textarea> with "
        "id 'hidden-content' populated exactly as `>{{ content }}</textarea>` without "
        "surrounding whitespace or newlines, so Monaco can read file contents from the DOM."
    )


@pytest.mark.unit
def test_editor_container_carries_the_file_name():
    """Verify that #editor-container carries data-file-name attribute."""
    html = _editor_pane_html()
    assert 'data-file-name="{{ name }}"' in html, (
        "Expected templates/partials/editor_pane.html to have a <div> with "
        "id 'editor-container' carrying `data-file-name=\"{{ name }}\"`."
    )


@pytest.mark.unit
def test_editor_pane_does_not_interpolate_content_into_javascript():
    """Verify that editor_pane.html contains neither safe_content nor backticks."""
    html = _editor_pane_html()
    assert "safe_content" not in html, (
        "Expected templates/partials/editor_pane.html to not reference 'safe_content', "
        "as content should be transported via the DOM rather than injected into JavaScript."
    )
    assert "`" not in html, (
        "Expected templates/partials/editor_pane.html to not contain any backtick characters (`), "
        "ensuring content is no longer interpolated inside a JS template literal."
    )


@pytest.mark.unit
def test_fetch_file_route_no_longer_escapes_content_for_javascript():
    """Verify that api/routes.py does not escape content or define safe_content."""
    code = _routes_py()
    assert "safe_content" not in code, (
        "Expected api/routes.py to not define or pass 'safe_content' in template context, "
        "as raw content is passed to the DOM directly."
    )
    assert r".replace('`', '\\`')" not in code, (
        "Expected api/routes.py to not contain the hand-rolled JS template literal escaping "
        "chain `.replace('`', '\\\\`')`."
    )
