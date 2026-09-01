"""Tests for the editor unsaved-changes indicator (Issue #188).

Covers:
- POST /api/save success path sets an HX-Trigger: quadlet-saved response
  header so the client can reliably know the save actually succeeded
  (both success and validation-failure paths return HTTP 200).
- POST /api/save validation-failure path does NOT set that header.
- static/modules/editor.js registers an htmx:confirm listener that guards
  #editor-pane swaps while its editorDirty flag is truthy.
- static/modules/editor.js listens for the quadlet-saved event and clears
  editorDirty.
- static/main.js's _beforeunloadHandler consults it through isEditorDirty().
- static/modules/editor.js tracks dirty state via Monaco's
  onDidChangeModelContent, and templates/partials/editor_pane.html exposes an
  #unsaved-indicator element. #468 moved the tracking out of the template.
"""
import os
import re

import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app

from tests.js_source import read_static_js

EDITOR_PANE_HTML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "partials", "editor_pane.html"
)


def _js():
    return read_static_js()


def _editor_pane_html():
    with open(EDITOR_PANE_HTML_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def client():
    with patch("core.config_loader.global_config.dev_auto_login", True):
        with TestClient(app) as test_client:
            yield test_client


# =============================================================================
# Server-side: /api/save HX-Trigger header
# =============================================================================


@pytest.mark.unit
def test_save_success_sets_quadlet_saved_trigger(client):
    with patch("api.routes.write_remote_file", new_callable=AsyncMock) as mock_write, \
         patch("api.routes.reload_and_restart", new_callable=AsyncMock) as mock_reload, \
         patch("api.routes.systemctl_action", new_callable=AsyncMock) as mock_status, \
         patch("api.routes.pool.execute_command", new_callable=AsyncMock) as mock_exec, \
         patch("api.routes.get_db_connection") as mock_conn:
        mock_write.return_value = None
        mock_reload.return_value = None
        mock_status.return_value = "active"
        mock_exec.return_value = "1234567890"

        mock_db = AsyncMock()
        mock_conn.return_value.__aenter__.return_value = mock_db

        response = client.post(
            "/api/save",
            data={
                "server_id": 1,
                "file_path": "/home/user/.config/containers/systemd/myapp.container",
                "scope": "user",
                "unit_name": "myapp",
                "content": "[Container]\nImage=nginx:latest\n",
            },
            follow_redirects=False,
        )

        assert response.status_code == 200
        assert response.headers.get("HX-Trigger") == "quadlet-saved"


@pytest.mark.unit
def test_save_validation_failure_has_no_trigger(client):
    # Missing the required "Image=" key makes validate_quadlet_syntax raise
    # QuadletValidationError, which _toast()'s the red "Validation error" path.
    response = client.post(
        "/api/save",
        data={
            "server_id": 1,
            "file_path": "/home/user/.config/containers/systemd/myapp.container",
            "scope": "user",
            "unit_name": "myapp",
            "content": "[Container]\nNetwork=host\n",
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Validation error" in response.text
    header = response.headers.get("HX-Trigger")
    assert header is None or "quadlet-saved" not in header


# =============================================================================
# Client-side: static/main.js source assertions
# =============================================================================


class TestMainJsDirtyTracking:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_htmx_confirm_listener_guards_editor_pane(self):
        assert "htmx:confirm" in self.js
        # Find the htmx:confirm listener block and make sure it references
        # both the editor pane target and the dirty flag.
        match = re.search(
            r"addEventListener\(\s*['\"]htmx:confirm['\"].*?\}\s*\)\s*;",
            self.js,
            re.DOTALL,
        )
        assert match, "expected an htmx:confirm event listener in main.js"
        block = match.group(0)
        assert "editor-pane" in block
        assert "editorDirty" in block
        assert "confirm(" in block

    @pytest.mark.unit
    def test_quadlet_saved_listener_clears_dirty_flag(self):
        match = re.search(
            r"addEventListener\(\s*['\"]quadlet-saved['\"].*?\}\s*\)\s*;",
            self.js,
            re.DOTALL,
        )
        assert match, "expected a quadlet-saved event listener in main.js"
        block = match.group(0)
        assert "editorDirty = false" in block

    @pytest.mark.unit
    def test_beforeunload_handler_checks_editor_dirty(self):
        match = re.search(
            r"function _beforeunloadHandler\(e\)\s*\{.*?\n\}",
            self.js,
            re.DOTALL,
        )
        assert match, "expected _beforeunloadHandler in main.js"
        assert "isEditorDirty()" in match.group(0)


# =============================================================================
# Client-side: templates/partials/editor_pane.html markup + dirty tracking
# =============================================================================


class TestEditorPaneTemplate:
    def setup_method(self):
        self.html = _editor_pane_html()

    @pytest.mark.unit
    def test_monaco_init_tracks_dirty_state(self):
        # The dirty tracking moved into mountEditorPane() in #468; the template
        # keeps only the indicator element the handler unhides.
        js = _js()
        assert "onDidChangeModelContent" in js
        assert "editorDirty = true" in js

    @pytest.mark.unit
    def test_unsaved_indicator_element_present(self):
        assert 'id="unsaved-indicator"' in self.html
