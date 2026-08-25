import pytest
"""
Tests for the session reconnect prompt (Issue #120).
Covers:
- beforeunload guard fires when terminals or log tail are active
- safeReload() saves session metadata then reloads without prompting
- qm-pending-reconnect storage format includes terminals and logTail
- Reconnect banner is injected on DOMContentLoaded when pending data exists
- _logTabs entries include serverId, unitName, scope for each open log tail
- _terminalTabs entries include serverId, containerName, scope, cmd
"""
import os
import re

from tests.js_source import read_static_js

HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")


def _js():
    return read_static_js()


def _html():
    with open(HTML_PATH, encoding="utf-8") as f:
        return f.read()


class TestBeforeunloadGuard:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_beforeunload_handler_registered(self):
        assert "addEventListener('beforeunload', _beforeunloadHandler)" in self.js

    @pytest.mark.unit
    def test_beforeunload_checks_terminal_tabs(self):
        assert "_terminalTabs.size" in self.js

    @pytest.mark.unit
    def test_beforeunload_checks_log_socket(self):
        pattern = r"_beforeunloadHandler[\s\S]{0,300}_logTabs\.size"
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_beforeunload_sets_return_value(self):
        assert "e.returnValue = ''" in self.js


class TestSafeReload:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_safe_reload_function_exists(self):
        assert "function safeReload(" in self.js

    @pytest.mark.unit
    def test_safe_reload_saves_sessions(self):
        assert "saveActiveSessionsToStorage" in self.js

    @pytest.mark.unit
    def test_safe_reload_removes_beforeunload_listener(self):
        assert "removeEventListener('beforeunload', _beforeunloadHandler)" in self.js

    @pytest.mark.unit
    def test_safe_reload_calls_location_reload(self):
        assert "window.location.reload()" in self.js


class TestSessionStorage:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_save_function_exists(self):
        assert "saveActiveSessionsToStorage" in self.js

    @pytest.mark.unit
    def test_pending_reconnect_key_used(self):
        assert "'qm-pending-reconnect'" in self.js

    @pytest.mark.unit
    def test_terminals_array_saved(self):
        assert "sessions.terminals" in self.js

    @pytest.mark.unit
    def test_log_tail_saved(self):
        assert "sessions.logTails" in self.js

    @pytest.mark.unit
    def test_terminal_entry_includes_server_id(self):
        assert "session.serverId" in self.js

    @pytest.mark.unit
    def test_terminal_entry_includes_container_name(self):
        assert "session.containerName" in self.js

    @pytest.mark.unit
    def test_terminal_entry_includes_scope(self):
        assert "session.scope" in self.js

    @pytest.mark.unit
    def test_terminal_entry_includes_cmd(self):
        assert "session.cmd" in self.js


class TestLogMetaTracking:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_log_tabs_map_exists(self):
        assert "const _logTabs = new Map()" in self.js

    @pytest.mark.unit
    def test_log_tab_stores_server_id(self):
        assert "serverId: serverId" in self.js

    @pytest.mark.unit
    def test_log_tab_stores_unit_name(self):
        assert "unitName: unitName" in self.js

    @pytest.mark.unit
    def test_log_tab_cleared_on_close(self):
        pattern = r"function\s+closeLogTab\s*\([\s\S]{0,500}_logTabs\.delete"
        assert re.search(pattern, self.js)


class TestTerminalTabMetadata:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_terminal_tab_stores_server_id(self):
        assert "serverId: serverId" in self.js

    @pytest.mark.unit
    def test_terminal_tab_stores_container_name(self):
        assert "containerName: containerName" in self.js

    @pytest.mark.unit
    def test_terminal_tab_stores_scope(self):
        assert "scope: scope" in self.js

    @pytest.mark.unit
    def test_terminal_tab_stores_cmd(self):
        assert "cmd: cmd" in self.js


class TestReconnectBanner:
    def setup_method(self):
        self.js = _js()

    @pytest.mark.unit
    def test_banner_injected_on_domcontentloaded(self):
        assert "reconnect-banner" in self.js

    @pytest.mark.unit
    def test_banner_reads_pending_reconnect(self):
        assert "localStorage.getItem('qm-pending-reconnect')" in self.js

    @pytest.mark.unit
    def test_banner_clears_pending_reconnect(self):
        assert "localStorage.removeItem('qm-pending-reconnect')" in self.js

    @pytest.mark.unit
    def test_reconnect_yes_calls_create_log_tab(self):
        pattern = r"reconnect-yes-btn[\s\S]{0,500}createLogTab"
        assert re.search(pattern, self.js)

    @pytest.mark.unit
    def test_reconnect_yes_calls_create_terminal_tab(self):
        assert "createTerminalTab" in self.js


class TestPanelReloadButton:
    def setup_method(self):
        self.html = _html()
        self.js = _js()

    @pytest.mark.unit
    def test_reload_button_exists(self):
        assert "panel-reload-btn" in self.html

    @pytest.mark.unit
    def test_reload_button_calls_soft_refresh(self):
        assert "softRefresh()" in self.html

    @pytest.mark.unit
    def test_soft_refresh_function_exists(self):
        assert "function softRefresh(" in self.js

    @pytest.mark.unit
    def test_soft_refresh_triggers_htmx_reload(self):
        assert "reload-servers" in self.js
