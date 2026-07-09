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


def _normalize_selector_variants(body):
    """Return a whitespace/quote-normalized version of a JS snippet for
    lenient substring checks against combined querySelectorAll selectors."""
    normalized = body.replace('"', "'")
    normalized = normalized.replace(", ", ",").replace(" ,", ",")
    return normalized


@pytest.mark.unit
def test_switch_functions_clear_active_across_both_chip_types():
    """Regression test for issue #163.

    Terminal tabs and log tabs share one chip strip (#terminal-conn-tabs) but
    switchTerminalTab and switchLogTab each only toggle .is-active on their
    own chip class, so a terminal chip and a log chip can both appear active
    at once. Both switch functions must clear .is-active across BOTH chip
    types via the combined selector '.terminal-conn-tab, .log-conn-tab'.
    """
    js = _read_js()

    terminal_start = js.index("window.switchTerminalTab = function")
    terminal_body = js[terminal_start:js.index("\n};", terminal_start)]

    log_start = js.index("window.switchLogTab = function")
    log_body = js[log_start:js.index("\n};", log_start)]

    combined_variants = (
        ".terminal-conn-tab, .log-conn-tab",
        ".terminal-conn-tab,.log-conn-tab",
    )

    terminal_normalized = _normalize_selector_variants(terminal_body)
    log_normalized = _normalize_selector_variants(log_body)
    normalized_variants = tuple(_normalize_selector_variants(v) for v in combined_variants)

    assert any(v in terminal_normalized for v in normalized_variants), (
        "switchTerminalTab must clear .is-active on both '.terminal-conn-tab' and "
        "'.log-conn-tab' chips (e.g. via querySelectorAll('.terminal-conn-tab, "
        ".log-conn-tab')) so a log chip does not remain highlighted after switching "
        "terminal tabs (issue #163)."
    )
    assert any(v in log_normalized for v in normalized_variants), (
        "switchLogTab must clear .is-active on both '.terminal-conn-tab' and "
        "'.log-conn-tab' chips (e.g. via querySelectorAll('.terminal-conn-tab, "
        ".log-conn-tab')) so a terminal chip does not remain highlighted after "
        "switching log tabs (issue #163)."
    )


@pytest.mark.unit
def test_chip_switch_functions_switch_bottom_mode():
    """Regression test for issue #163.

    Clicking a terminal or log chip only switches the active session within
    its own tab set; it does not switch the bottom-panel mode (Terminal vs
    Logs pane visibility via switchBottomTab). So clicking a log chip while
    the Terminal pane is showing does not reveal the Logs pane. Both
    switchTerminalTab and switchLogTab must call switchBottomTab with the
    corresponding mode.
    """
    js = _read_js()

    terminal_start = js.index("window.switchTerminalTab = function")
    terminal_body = js[terminal_start:js.index("\n};", terminal_start)]

    log_start = js.index("window.switchLogTab = function")
    log_body = js[log_start:js.index("\n};", log_start)]

    terminal_variants = ("switchBottomTab('terminal')", 'switchBottomTab("terminal")')
    log_variants = ("switchBottomTab('logs')", 'switchBottomTab("logs")')

    assert any(v in terminal_body for v in terminal_variants), (
        "switchTerminalTab must call switchBottomTab('terminal') so clicking a "
        "terminal chip also switches the bottom panel into Terminal mode (issue #163)."
    )
    assert any(v in log_body for v in log_variants), (
        "switchLogTab must call switchBottomTab('logs') so clicking a log chip "
        "also switches the bottom panel into Logs mode (issue #163)."
    )


@pytest.mark.unit
def test_switch_bottom_tab_reapplies_chip_highlight():
    """Regression test for issue #163.

    switchBottomTab currently only references window._activeTerminalTabKey
    (to re-fit the terminal), so switching the bottom-panel mode does not
    re-apply chip highlighting for the incoming mode. It must also reference
    window._activeLogTabKey so the correct chip (terminal or log) is
    re-highlighted after a mode switch.
    """
    js = _read_js()
    switchtab_start = js.index("window.switchBottomTab = function")
    switchtab_body = js[switchtab_start:js.index("\n};", switchtab_start)]

    assert "_activeTerminalTabKey" in switchtab_body, (
        "Expected switchBottomTab to still reference window._activeTerminalTabKey."
    )
    assert "_activeLogTabKey" in switchtab_body, (
        "switchBottomTab must also reference window._activeLogTabKey so that "
        "switching to Logs mode re-applies the active-chip highlight to the "
        "current log tab, not just the terminal tab (issue #163)."
    )
