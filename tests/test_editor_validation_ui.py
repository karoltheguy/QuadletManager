"""Tests for the editor-side validation UI (Issue #194).

Covers:
- templates/partials/editor_pane.html gains a #validate-btn that calls
  validateQuadlet(...) and lives inside the `{% if user_role == 'editor' %}`
  block that wraps the Save button, so viewers cannot see or trigger it.
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
    def test_validate_button_is_gated_to_editor_role(self):
        # The Validate button must only be rendered for the editor role,
        # so it must live inside the same {% if user_role == 'editor' %}
        # guard block that wraps the Save button.
        start = self.html.index("{% if user_role == 'editor' %}")
        end = self.html.index("{% endif %}", start) + len("{% endif %}")
        editor_guard_block = self.html[start:end]

        assert "validate-btn" in editor_guard_block, (
            "validate-btn must be inside the {% if user_role == 'editor' %} "
            "guard block so viewers cannot see or trigger it"
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

    @pytest.mark.unit
    def test_validate_quadlet_surfaces_error_body_on_non_ok_response(self):
        # When /api/validate/{server_id} responds with a non-OK status (e.g.
        # 502 with {"error": "Validation failed (ref: abc123)"}), that body
        # is currently discarded: the code only throws a generic status-code
        # error. The user never sees the real error or a ref they can search
        # server logs for. The `if (!response.ok) { ... }` block must read
        # the JSON error body and render it into #validation-results so the
        # message reaches the user, while still throwing so saveQuadlet can
        # tell "could not validate" apart from "invalid".
        match = re.search(
            r"if \(!response\.ok\) \{.*?\n    \}",
            self.js,
            re.DOTALL,
        )
        assert match, "expected to locate the `if (!response.ok) { ... }` block in validateQuadlet"
        block = match.group(0)

        assert "json()" in block, (
            "the non-ok branch of validateQuadlet must call response.json() to read "
            "the {\"error\": ...} body instead of discarding it"
        )
        assert "validation-results" in block, (
            "the non-ok branch of validateQuadlet must render the error body into "
            "#validation-results so the user actually sees it"
        )
        assert "throw" in block, (
            "the non-ok branch must still throw so saveQuadlet can distinguish "
            "'could not validate' from 'invalid'"
        )


# =============================================================================
# Client-side: templates/partials/editor_pane.html #validate-btn error handling
# =============================================================================


class TestValidateButtonErrorHandling:
    def setup_method(self):
        self.html = _editor_pane_html()

    @pytest.mark.unit
    def test_validate_button_handles_validation_rejection(self):
        # validateQuadlet() throws when the request fails or the server
        # returns a non-ok status. Called bare from onclick, that rejection
        # is unhandled and the user sees nothing. The #validate-btn onclick
        # must chain a .catch( to handle that rejection.
        match = re.search(
            r'<button[^>]*id="validate-btn"[^>]*onclick="([^"]*)"',
            self.html,
        )
        assert match, "expected a button with id=\"validate-btn\" in editor_pane.html"
        onclick = match.group(1)
        assert ".catch(" in onclick, (
            "#validate-btn onclick must chain .catch( onto validateQuadlet() so a "
            "rejected validation request is handled instead of becoming an "
            "unhandled promise rejection"
        )
