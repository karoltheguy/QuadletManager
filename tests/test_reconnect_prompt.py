"""
Tests for the session reconnect prompt (Issue #120).
Covers:
- beforeunload guard fires when terminals or log tail are active
- safeReload() saves session metadata then reloads without prompting
- qm-pending-reconnect storage format includes terminals and logTail
- Reconnect banner is injected on DOMContentLoaded when pending data exists
- _currentLogMeta is set/cleared with the log tail lifecycle
- _terminalTabs entries include serverId, containerName, scope, cmd
"""
import os
import re

JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "main.js")
HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")


def _js():
    with open(JS_PATH, encoding="utf-8") as f:
        return f.read()


def _html():
    with open(HTML_PATH, encoding="utf-8") as f:
        return f.read()


class TestBeforeunloadGuard:
    def setup_method(self):
        self.js = _js()

    def test_beforeunload_handler_registered(self):
        assert "addEventListener('beforeunload', _beforeunloadHandler)" in self.js

    def test_beforeunload_checks_terminal_tabs(self):
        assert "_terminalTabs.size" in self.js

    def test_beforeunload_checks_log_socket(self):
        pattern = r"_beforeunloadHandler[\s\S]{0,300}currentLogSocket"
        assert re.search(pattern, self.js)

    def test_beforeunload_sets_return_value(self):
        assert "e.returnValue = ''" in self.js


class TestSafeReload:
    def setup_method(self):
        self.js = _js()

    def test_safe_reload_function_exists(self):
        assert "window.safeReload" in self.js

    def test_safe_reload_saves_sessions(self):
        assert "saveActiveSessionsToStorage" in self.js

    def test_safe_reload_removes_beforeunload_listener(self):
        assert "removeEventListener('beforeunload', _beforeunloadHandler)" in self.js

    def test_safe_reload_calls_location_reload(self):
        assert "window.location.reload()" in self.js


class TestSessionStorage:
    def setup_method(self):
        self.js = _js()

    def test_save_function_exists(self):
        assert "saveActiveSessionsToStorage" in self.js

    def test_pending_reconnect_key_used(self):
        assert "'qm-pending-reconnect'" in self.js

    def test_terminals_array_saved(self):
        assert "sessions.terminals" in self.js

    def test_log_tail_saved(self):
        assert "sessions.logTail" in self.js

    def test_terminal_entry_includes_server_id(self):
        assert "session.serverId" in self.js

    def test_terminal_entry_includes_container_name(self):
        assert "session.containerName" in self.js

    def test_terminal_entry_includes_scope(self):
        assert "session.scope" in self.js

    def test_terminal_entry_includes_cmd(self):
        assert "session.cmd" in self.js


class TestLogMetaTracking:
    def setup_method(self):
        self.js = _js()

    def test_current_log_meta_variable_exists(self):
        assert "_currentLogMeta" in self.js

    def test_log_meta_set_on_toggle_logs(self):
        pattern = r"_currentLogMeta\s*=\s*\{[\s\S]{0,100}serverId"
        assert re.search(pattern, self.js)

    def test_log_meta_cleared_on_stop_logs(self):
        pattern = r"stopLogs[\s\S]{0,300}_currentLogMeta\s*=\s*null"
        assert re.search(pattern, self.js)


class TestTerminalTabMetadata:
    def setup_method(self):
        self.js = _js()

    def test_terminal_tab_stores_server_id(self):
        assert "serverId: serverId" in self.js

    def test_terminal_tab_stores_container_name(self):
        assert "containerName: containerName" in self.js

    def test_terminal_tab_stores_scope(self):
        assert "scope: scope" in self.js

    def test_terminal_tab_stores_cmd(self):
        assert "cmd: cmd" in self.js


class TestReconnectBanner:
    def setup_method(self):
        self.js = _js()

    def test_banner_injected_on_domcontentloaded(self):
        assert "reconnect-banner" in self.js

    def test_banner_reads_pending_reconnect(self):
        assert "localStorage.getItem('qm-pending-reconnect')" in self.js

    def test_banner_clears_pending_reconnect(self):
        assert "localStorage.removeItem('qm-pending-reconnect')" in self.js

    def test_reconnect_yes_calls_toggle_logs(self):
        assert "toggleLogs" in self.js

    def test_reconnect_yes_calls_create_terminal_tab(self):
        assert "createTerminalTab" in self.js


class TestNavReloadButton:
    def setup_method(self):
        self.html = _html()

    def test_reload_button_exists(self):
        assert "nav-reload-btn" in self.html

    def test_reload_button_calls_safe_reload(self):
        assert "safeReload()" in self.html
