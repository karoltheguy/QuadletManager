"""Tests for the editor-side validation UI (Issue #194).

Covers:
- templates/partials/editor_pane.html gains a #validate-btn that calls
  validateQuadlet(...) and is visible to both editors and viewers (i.e.
  it lives outside the `{% if user_role == 'editor' %}` block that wraps
  the Save button).
- templates/partials/editor_pane.html gains a #validation-results div
  that appears after the #editor-container div, so validation output
  can be rendered near the editor.
- The Save button (#save-btn) is rewired to call saveQuadlet(...) instead
  of directly dispatching a submit event inline.
- static/main.js defines validateQuadlet(), which POSTs to
  /api/validate/, feeds Monaco's setModelMarkers with the results, and
  renders them into #validation-results.
- static/main.js defines saveQuadlet(), which calls validateQuadlet(),
  prompts via confirm() to save anyway on validation issues, still
  performs the existing copy-content-into-hidden-textarea-and-submit
  behavior (#save-form / #hidden-content), and tolerates the validation
  call failing (try/catch) so save always proceeds even if validation is
  unavailable.
"""
import os
import re

import pytest

JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "main.js")
EDITOR_PANE_HTML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "partials", "editor_pane.html"
)


def _js():
    with open(JS_PATH, encoding="utf-8") as f:
        return f.read()


def _editor_pane_html():
    with open(EDITOR_PANE_HTML_PATH, encoding="utf-8") as f:
        return f.read()


# =============================================================================
# Client-side: templates/partials/editor_pane.html markup
# =============================================================================


class TestEditorPaneValidationMarkup:
    def setup_method(self):
        self.html = _editor_pane_html()

    @pytest.mark.unit
    def test_validate_btn_present_and_calls_validate_quadlet(self):
        match = re.search(
            r'<button[^>]*id="validate-btn"[^>]*onclick="([^"]*)"',
            self.html,
        )
        assert match, "expected a button with id=\"validate-btn\" in editor_pane.html"
        assert "validateQuadlet(" in match.group(1)

    @pytest.mark.unit
    def test_validate_btn_visible_to_viewers_not_just_editors(self):
        assert "validate-btn" in self.html

        # Locate the {% if user_role == 'editor' %} ... {% endif %} block that
        # wraps the Save button, and make sure validate-btn is NOT inside it.
        start = self.html.index("{% if user_role == 'editor' %}")
        end = self.html.index("{% endif %}", start) + len("{% endif %}")
        save_guard_block = self.html[start:end]

        assert "save-btn" in save_guard_block, (
            "sanity check: the editor-only guard should still wrap the save button"
        )
        assert "validate-btn" not in save_guard_block, (
            "validate-btn must be visible to viewers, so it must live outside "
            "the {% if user_role == 'editor' %} guard that wraps the save button"
        )

    @pytest.mark.unit
    def test_validation_results_div_present_after_editor_container(self):
        assert 'id="validation-results"' in self.html

        editor_container_idx = self.html.index('id="editor-container"')
        validation_results_idx = self.html.index('id="validation-results"')
        assert validation_results_idx > editor_container_idx, (
            "#validation-results must appear after #editor-container"
        )

    @pytest.mark.unit
    def test_save_btn_calls_save_quadlet_not_inline_dispatch(self):
        match = re.search(
            r'<button[^>]*id="save-btn"[^>]*onclick="([^"]*)"',
            self.html,
        )
        assert match, "expected a button with id=\"save-btn\" in editor_pane.html"
        onclick = match.group(1)
        assert "saveQuadlet(" in onclick
        assert "dispatchEvent(new Event('submit'" not in onclick


# =============================================================================
# Client-side: static/main.js validateQuadlet / saveQuadlet
# =============================================================================


class TestMainJsValidation:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_validate_quadlet_function_defined(self):
        assert (
            "async function validateQuadlet" in self.js
            or "window.validateQuadlet =" in self.js
        ), "expected validateQuadlet to be defined in main.js"

    @pytest.mark.unit
    def test_validate_quadlet_hits_api_and_uses_monaco_markers(self):
        assert "/api/validate/" in self.js
        assert "setModelMarkers" in self.js
        assert "validation-results" in self.js

    @pytest.mark.unit
    def test_save_quadlet_function_defined(self):
        assert (
            "async function saveQuadlet" in self.js
            or "window.saveQuadlet =" in self.js
        ), "expected saveQuadlet to be defined in main.js"

    @pytest.mark.unit
    def test_save_quadlet_calls_validate_and_confirms_save_anyway(self):
        match = re.search(
            r"(async function saveQuadlet|window\.saveQuadlet\s*=\s*(?:async\s*)?function)"
            r"\s*\([^)]*\)\s*\{.*",
            self.js,
            re.DOTALL,
        )
        assert match, "expected to locate the saveQuadlet function body in main.js"
        body = match.group(0)

        assert "validateQuadlet(" in body
        assert "confirm(" in body
        assert "save-form" in body
        assert "hidden-content" in body

    @pytest.mark.unit
    def test_save_quadlet_tolerates_validation_failure(self):
        # Keep this assertion simple and honest: locate the saveQuadlet
        # definition and check that a `catch` shows up within a reasonable
        # window afterward, indicating validation errors are swallowed so
        # save can still proceed.
        idx = self.js.find("function saveQuadlet")
        assert idx != -1, "expected to locate the saveQuadlet function in main.js"
        window = self.js[idx: idx + 2000]
        assert "catch" in window, (
            "saveQuadlet must tolerate a failed/unavailable validation call "
            "(try/catch or .catch) so save still proceeds"
        )
