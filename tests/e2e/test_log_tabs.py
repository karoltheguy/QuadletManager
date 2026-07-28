"""E2E tests for mode-independent, multi-session log tabs (issue #123).

Mirrors tests/e2e/test_terminal_connect.py's mocking approach, but intercepts
/ws/logs/ instead of /ws/exec/. Only the backend (localhost:8000) needs to be
running; no live container needed.
"""
import pytest
from playwright.sync_api import Page, expect

_WS_MOCK_INIT = """
(function () {
    var _OrigWS = window.WebSocket;

    window._mockLogWsRegistry = {};

    function MockLogWS(url, protocols) {
        this.url = url;
        this.readyState = 0;          // CONNECTING
        this.onopen = null;
        this.onclose = null;
        this.onmessage = null;
        this.onerror = null;
        window._mockLogWsRegistry[url] = this;

        var self = this;
        setTimeout(function () {
            self.readyState = 1;      // OPEN
            if (self.onopen) self.onopen(new Event('open'));
        }, 10);
    }
    MockLogWS.prototype.send = function (data) {
        if (!this._sent) this._sent = [];
        this._sent.push(data);
    };
    MockLogWS.prototype.close = function (code, reason) {
        this.readyState = 3;          // CLOSED
        if (this.onclose) {
            this.onclose({ code: code || 1000, reason: reason || '' });
        }
    };
    MockLogWS.CONNECTING = 0;
    MockLogWS.OPEN = 1;
    MockLogWS.CLOSING = 2;
    MockLogWS.CLOSED = 3;

    window.WebSocket = function (url, protocols) {
        if (typeof url === 'string' && url.indexOf('/ws/logs/') !== -1) {
            return new MockLogWS(url, protocols);
        }
        return new _OrigWS(url, protocols);
    };
    Object.assign(window.WebSocket, {
        CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3
    });

    window._closeMockLogWsByUrlPart = function (urlPart) {
        Object.keys(window._mockLogWsRegistry).forEach(function (url) {
            if (url.indexOf(urlPart) !== -1) {
                window._mockLogWsRegistry[url].close(1001, 'test close');
            }
        });
    };
})();
"""

_SSE_MOCK_INIT = """
(function () {
    window.EventSource = function (url) {
        this.url = url;
        this.readyState = 0;
        this.addEventListener = function () {};
        this.close = function () {};
    };
})();
"""


def _goto_or_skip(page: Page) -> None:
    page.add_init_script(_SSE_MOCK_INIT)
    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")
    page.locator("#navigator").get_by_text("Loading servers...").wait_for(state="hidden")
    page.wait_for_function("typeof window.runningContainersBySid !== 'undefined'")


def _inject_prerequisites(
    page: Page,
    stem: str = "myapp",
    server_id: int = 1,
    server_name: str = "Mock Server",
) -> None:
    page.evaluate(f"""() => {{
        window._selectedContainerStem = '{stem}';
        window._selectedContainerServerId = {server_id};
        window._selectedContainerScope = 'global';
        window.runningContainersBySid[{server_id}] = new Set(['{stem}']);

        lastStatsPerServer[{server_id}] = {{
            server_id: {server_id},
            server_name: '{server_name}',
            containers: []
        }};
    }}""")


def _open_logs_pane(page: Page) -> None:
    page.click("button.nav-item:has-text('Containers')")
    page.evaluate("openBottomPanel('logs')")
    expect(page.locator("#bottom-logs-pane")).to_be_visible()


def _click_tail_logs(page: Page) -> None:
    page.click("#toggle-logs-btn", force=True)
    page.wait_for_timeout(100)


@pytest.mark.e2e
def test_tail_logs_creates_chip(page: Page):
    """Clicking Tail Logs creates a .log-conn-tab chip in the shared sessions strip."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_logs_pane(page)

    _click_tail_logs(page)

    expect(page.locator(".log-conn-tab")).to_have_count(1)


@pytest.mark.e2e
def test_second_log_session_opens_second_chip(page: Page):
    """Tailing a second, different unit opens a second simultaneous log chip."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)

    _inject_prerequisites(page, stem="alpha", server_id=1, server_name="Mock Server")
    _open_logs_pane(page)
    _click_tail_logs(page)

    page.evaluate("""() => {
        window._selectedContainerStem = 'beta';
        window.runningContainersBySid[1].add('beta');
    }""")
    _click_tail_logs(page)

    expect(page.locator(".log-conn-tab")).to_have_count(2)


@pytest.mark.e2e
def test_tail_same_unit_twice_switches_instead_of_duplicating(page: Page):
    """Clicking Tail Logs twice for the same container switches to the existing tab."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_logs_pane(page)

    _click_tail_logs(page)
    _click_tail_logs(page)

    expect(page.locator(".log-conn-tab")).to_have_count(1)


@pytest.mark.e2e
def test_switching_mode_tabs_preserves_both_chip_kinds(page: Page):
    """Opening a terminal session and a log session, then flipping mode tabs,
    must not destroy or hide either chip from the shared sessions strip."""
    page.add_init_script(_WS_MOCK_INIT)
    page.add_init_script("""
    (function () {
        var _OrigWS = window.WebSocket;
        window.WebSocket = function (url, protocols) {
            if (typeof url === 'string' && url.indexOf('/ws/exec/') !== -1) {
                var ws = { readyState: 1, send: function(){}, close: function(){} };
                setTimeout(function () { if (ws.onopen) ws.onopen(new Event('open')); }, 10);
                return ws;
            }
            return new _OrigWS(url, protocols);
        };
        Object.assign(window.WebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });
    })();
    """)
    _goto_or_skip(page)
    _inject_prerequisites(page)

    # Open a log session first.
    _open_logs_pane(page)
    _click_tail_logs(page)
    expect(page.locator(".log-conn-tab")).to_have_count(1)

    # Switch to Terminal mode and connect a terminal session too.
    page.evaluate("""() => {
        window._fitAddonLoaded = true;
        if (!window.FitAddon) {
            window.FitAddon = {
                FitAddon: class {
                    fit() {}
                    proposeDimensions() { return { cols: 80, rows: 24 }; }
                    activate(t) {}
                }
            };
        }
    }""")
    page.evaluate("switchBottomTab('terminal')")
    page.evaluate("var btn = document.getElementById('terminal-connect-btn'); if(btn) btn.disabled = false;")
    page.click("#terminal-connect-btn", force=True)
    page.wait_for_timeout(100)
    expect(page.locator(".terminal-conn-tab")).to_have_count(1)

    # Both chips must coexist regardless of which mode tab is active.
    expect(page.locator(".log-conn-tab")).to_have_count(1)

    page.evaluate("switchBottomTab('logs')")
    expect(page.locator(".terminal-conn-tab")).to_have_count(1)
    expect(page.locator(".log-conn-tab")).to_have_count(1)


@pytest.mark.e2e
def test_close_log_chip_stops_websocket(page: Page):
    """Clicking x on a log chip removes it and closes its WebSocket."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_logs_pane(page)

    _click_tail_logs(page)
    expect(page.locator(".log-conn-tab")).to_have_count(1)

    page.locator(".log-conn-tab-close").click()
    page.wait_for_timeout(200)

    expect(page.locator(".log-conn-tab")).to_have_count(0, timeout=5000)

    closed = page.evaluate("""() => {
        var reg = window._mockLogWsRegistry;
        return Object.keys(reg).some(function(url) {
            return url.indexOf('/ws/logs/') !== -1 && reg[url].readyState === 3;
        });
    }""")
    assert closed, "Expected the mock log WebSocket to be closed after the chip's × was clicked."


@pytest.mark.e2e
def test_log_empty_hint_reappears_after_last_chip_closed(page: Page):
    """After the last log tab is closed, the empty-state hint reappears."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_logs_pane(page)

    _click_tail_logs(page)
    page.locator(".log-conn-tab-close").click()
    page.wait_for_timeout(200)

    hint = page.locator("#log-empty-hint")
    expect(hint).to_be_visible()
