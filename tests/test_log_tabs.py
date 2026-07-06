"""Source-structure tests for mode-independent, multi-session log tabs (issue #123).

Verifies:
- Log sessions are tracked in a `_logTabs` Map (mirroring `_terminalTabs`), not a
  single `currentLogSocket` variable.
- Dedicated create/switch/close functions exist for log tabs, mirroring the
  terminal tab lifecycle functions.
- Log chips render into the same shared sessions strip as terminal chips.
- Switching the Terminal/Logs mode tab does not clear the shared sessions strip.
"""
import os
import pytest

JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "main.js")


def _read_js():
    with open(JS_PATH) as f:
        return f.read()


@pytest.mark.unit
def test_log_tabs_map_replaces_singular_log_socket():
    js = _read_js()
    assert "window._logTabs = new Map()" in js, (
        "Expected window._logTabs = new Map() mirroring window._terminalTabs, "
        "to support multiple simultaneous named log sessions."
    )
    assert "let currentLogSocket" not in js and "var currentLogSocket" not in js, (
        "The old singular currentLogSocket variable should be removed in favor of _logTabs."
    )


@pytest.mark.unit
def test_log_tab_lifecycle_functions_exist():
    js = _read_js()
    for fn in ("createLogTab", "switchLogTab", "closeLogTab"):
        assert fn in js, f"Expected a {fn}() function mirroring the terminal tab lifecycle."


@pytest.mark.unit
def test_log_chips_render_into_shared_sessions_strip():
    js = _read_js()
    assert "log-conn-tab" in js, (
        "Expected log chips to use a distinct '.log-conn-tab' class (mirroring "
        "'.terminal-conn-tab') so they can be styled differently while sharing the strip."
    )
    assert "getElementById('terminal-conn-tabs')" in js, (
        "Log chips must be appended into the same shared sessions-strip container "
        "used by terminal chips (#terminal-conn-tabs), not a separate strip."
    )


@pytest.mark.unit
def test_switch_bottom_tab_does_not_clear_sessions_strip():
    js = _read_js()
    switchtab_start = js.index("window.switchBottomTab = function")
    switchtab_body = js[switchtab_start:js.index("\n};", switchtab_start)]

    destructive_calls = ("innerHTML = ''", "innerHTML=''", ".remove()")
    strip_related = "terminal-conn-tabs" in switchtab_body or "bottom-panel-sessions-strip" in switchtab_body
    assert not (strip_related and any(c in switchtab_body for c in destructive_calls)), (
        "switchBottomTab must not clear/destroy the sessions strip or its chips when "
        "switching between Terminal and Logs mode."
    )
