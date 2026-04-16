"""E2E tests for terminal Connect/Disconnect button lifecycle.

Architecture note — two mocking layers:
  1. window.WebSocket monkeypatch (add_init_script): Intercepts only /ws/exec/
     connections and replaces them with a controllable mock.  Playwright's
     route_web_socket() does not intercept localhost WS connections, so we
     patch the constructor directly.  The mock auto-fires onopen after 10 ms
     so the existing JS onopen handler runs unchanged.  window._closeTerminalWs()
     is exposed so tests can simulate a server-side close.

  2. FitAddon stub (page.evaluate before click): The CDN for xterm-addon-fit
     is unreachable in this environment so loadFitAddon's onerror path fires.
     We inject a lightweight stub so the resize handshake runs and
     proposeDimensions returns a valid size.

Only the backend (localhost:8000) needs to be running; no live container needed.
"""
import json
import pytest
from playwright.sync_api import Page, expect


# ── Shared JS injected as an init script ─────────────────────────────────────

_WS_MOCK_INIT = """
(function () {
    var _OrigWS = window.WebSocket;

    function MockExecWS(url, protocols) {
        this.url = url;
        this.readyState = 0;          // CONNECTING
        this.onopen = null;
        this.onclose = null;
        this.onmessage = null;
        this.onerror = null;
        window._mockWsInstance = this;
        window._mockWsSent = [];

        var self = this;
        setTimeout(function () {
            self.readyState = 1;      // OPEN
            if (self.onopen) self.onopen(new Event('open'));
        }, 10);
    }
    MockExecWS.prototype.send = function (data) {
        window._mockWsSent.push(data);
    };
    MockExecWS.prototype.close = function (code, reason) {
        this.readyState = 3;          // CLOSED
        if (this.onclose) {
            this.onclose({ code: code || 1000, reason: reason || '' });
        }
    };
    MockExecWS.CONNECTING = 0;
    MockExecWS.OPEN = 1;
    MockExecWS.CLOSING = 2;
    MockExecWS.CLOSED = 3;

    // Keep the real WebSocket for everything except exec tunnels.
    window.WebSocket = function (url, protocols) {
        if (typeof url === 'string' && url.indexOf('/ws/exec/') !== -1) {
            return new MockExecWS(url, protocols);
        }
        return new _OrigWS(url, protocols);
    };
    Object.assign(window.WebSocket, {
        CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3
    });

    // Test helper: simulate server-side close.
    window._closeTerminalWs = function (code, reason) {
        var ws = window._mockWsInstance;
        if (ws) ws.close(code || 1001, reason || '');
    };
})();
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _goto_or_skip(page: Page) -> None:
    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend is not running locally on 8000 for E2E tests.")
    page.locator("text='Loading servers...'").wait_for(state="hidden")


def _inject_prerequisites(page: Page, stem: str = "myapp", server_id: int = 1) -> None:
    """Set JS globals so connectTerminal() sees a running container, and
    inject a FitAddon stub so the resize handshake fires correctly."""
    page.evaluate(f"""() => {{
        // Container state
        window._selectedContainerStem = '{stem}';
        window._selectedContainerServerId = {server_id};
        runningContainersBySid[{server_id}] = new Set(['{stem}']);

        // FitAddon stub (CDN unreachable in test env; loadFitAddon's onerror
        // path fires but we can pre-set the addon so onopen sends a resize).
        window._fitAddonLoaded = true;
        if (!window.FitAddon) {{
            window.FitAddon = {{
                FitAddon: class {{
                    fit() {{}}
                    proposeDimensions() {{ return {{ cols: 80, rows: 24 }}; }}
                    activate(t) {{}}
                }}
            }};
        }}
        // If the FitAddon instance was already created (e.g. from a prior
        // connectTerminal call that used the onerror path), replace it.
        window._terminalFitAddon = new window.FitAddon.FitAddon();
        if (window._terminalInstance) {{
            window._terminalInstance.loadAddon(window._terminalFitAddon);
        }}
    }}""")


def _open_terminal_tab(page: Page) -> None:
    page.click("button.nav-item:has-text('Containers')")
    page.evaluate("openBottomPanel('terminal')")
    expect(page.locator("#bottom-terminal-pane")).to_be_visible()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_terminal_connect_shows_disconnect_button(page: Page):
    """Happy path: Connect opens a WS and swaps the button to Disconnect.

    The mock WS stays open (no close triggered), so the button must remain
    in Disconnected state for the life of the assertion window.
    """
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_terminal_tab(page)

    page.click("#terminal-connect-btn")

    # onopen fires after 10 ms → Connect hidden, Disconnect visible
    expect(page.locator("#terminal-disconnect-btn")).to_be_visible(timeout=5000)
    expect(page.locator("#terminal-connect-btn")).to_be_hidden()

    # Verify the WS was actually created for the correct URL
    ws_url = page.evaluate("() => window._mockWsInstance ? window._mockWsInstance.url : null")
    assert ws_url and "/ws/exec/" in ws_url, f"Expected /ws/exec/ WS URL, got: {ws_url}"


def test_terminal_immediate_ws_close_reverts_to_connect(page: Page):
    """Issue #100 regression: WS closes immediately after open.

    When the server drops the connection right away, onclose must revert the
    button to Connect so the user can retry.
    """
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_terminal_tab(page)

    page.click("#terminal-connect-btn")

    # Wait for the WS to open (mock fires onopen after 10 ms)
    expect(page.locator("#terminal-disconnect-btn")).to_be_visible(timeout=5000)

    # Simulate the server immediately dropping the connection
    page.evaluate("window._closeTerminalWs(1001, 'exec failed')")

    # onclose must revert button to Connect
    expect(page.locator("#terminal-connect-btn")).to_be_visible(timeout=3000)
    expect(page.locator("#terminal-disconnect-btn")).to_be_hidden()


def test_terminal_disconnect_button_closes_session(page: Page):
    """Full round-trip: connect → session active → disconnect → idle."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_terminal_tab(page)

    page.click("#terminal-connect-btn")
    expect(page.locator("#terminal-disconnect-btn")).to_be_visible(timeout=5000)

    page.click("#terminal-disconnect-btn")

    expect(page.locator("#terminal-connect-btn")).to_be_visible(timeout=3000)
    expect(page.locator("#terminal-disconnect-btn")).to_be_hidden()


def test_terminal_connect_sends_resize_message(page: Page):
    """On connect, the JS sends a resize JSON message to the WS.

    This verifies the FitAddon handshake is wired correctly — the PTY needs
    initial dimensions to allocate the right number of rows/cols.
    """
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_terminal_tab(page)

    page.click("#terminal-connect-btn")
    expect(page.locator("#terminal-disconnect-btn")).to_be_visible(timeout=5000)

    # Give onopen a tick to send the resize message
    page.wait_for_timeout(200)

    sent = page.evaluate("() => window._mockWsSent || []")
    resize_msgs = [m for m in sent if _is_resize_message(m)]
    assert resize_msgs, (
        f"No resize message sent to WS after connect. Messages sent: {sent}"
    )
    dims = json.loads(resize_msgs[0])
    assert dims["cols"] > 0 and dims.get("rows", dims.get("height", 1)) > 0


def _is_resize_message(msg) -> bool:
    try:
        data = json.loads(msg)
        return data.get("type") == "resize" and "cols" in data
    except Exception:
        return False
