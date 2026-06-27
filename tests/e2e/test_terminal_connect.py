"""E2E tests for multi-tab terminal session management (issue #85).

Architecture note — two mocking layers:
  1. window.WebSocket monkeypatch (add_init_script): Intercepts only /ws/exec/
     connections and replaces them with a controllable mock.  Tracks all
     created instances by tab key so tests can close individual tabs.
     window._closeMockWs(key) simulates a server-side close for a specific tab.

  2. FitAddon stub (injected via _inject_prerequisites): CDN unreachable in
     test env; we provide a lightweight stub directly so the resize handshake
     and fitAddon.fit() calls don't throw.

Only the backend (localhost:8000) needs to be running; no live container needed.
"""
import json
import pytest
from playwright.sync_api import Page, expect


# ── Shared JS injected as an init script ─────────────────────────────────────

_WS_MOCK_INIT = """
(function () {
    var _OrigWS = window.WebSocket;

    // Registry: tabKey → MockExecWS instance
    window._mockWsRegistry = {};

    function MockExecWS(url, protocols) {
        this.url = url;
        this.readyState = 0;          // CONNECTING
        this.onopen = null;
        this.onclose = null;
        this.onmessage = null;
        this.onerror = null;
        window._mockWsRegistry[url] = this;

        var self = this;
        setTimeout(function () {
            self.readyState = 1;      // OPEN
            if (self.onopen) self.onopen(new Event('open'));
        }, 10);
    }
    MockExecWS.prototype.send = function (data) {
        if (!this._sent) this._sent = [];
        this._sent.push(data);
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

    // Test helper: simulate server-side close for a given WS URL substring.
    window._closeMockWsByUrlPart = function (urlPart) {
        Object.keys(window._mockWsRegistry).forEach(function (url) {
            if (url.indexOf(urlPart) !== -1) {
                window._mockWsRegistry[url].close(1001, 'test close');
            }
        });
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
    page.wait_for_function("typeof window.runningContainersBySid !== 'undefined'")


def _inject_prerequisites(
    page: Page,
    stem: str = "myapp",
    server_id: int = 1,
    server_name: str = "testserver",
) -> None:
    """Set JS globals so connectTerminal() sees a running container, and
    inject a FitAddon stub so the resize handshake fires without CDN access."""
    page.evaluate(f"""() => {{
        window._selectedContainerStem = '{stem}';
        window._selectedContainerServerId = {server_id};
        window.runningContainersBySid[{server_id}] = new Set(['{stem}']);

        // Populate lastStatsPerServer so the tab label resolves correctly.
        lastStatsPerServer[{server_id}] = {{
            server_id: {server_id},
            server_name: '{server_name}',
            containers: []
        }};

        // FitAddon stub — CDN unreachable in test env.
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
    }}""")


def _open_terminal_pane(page: Page) -> None:
    page.click("button.nav-item:has-text('Containers')")
    page.evaluate("openBottomPanel('terminal')")
    expect(page.locator("#bottom-terminal-pane")).to_be_visible()


def _click_connect(page: Page) -> None:
    page.evaluate("var btn = document.getElementById('terminal-connect-btn'); if(btn) btn.disabled = false;")
    page.click("#terminal-connect-btn", force=True)
    # Wait for the mock WS onopen (10 ms) + tab render
    page.wait_for_timeout(100)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.e2e
def test_connect_creates_tab(page: Page):
    """Clicking Connect creates a terminal-conn-tab in the tab strip."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_terminal_pane(page)

    _click_connect(page)

    tabs = page.locator(".terminal-conn-tab")
    expect(tabs).to_have_count(1)


@pytest.mark.e2e
def test_tab_label_uses_server_name_and_container(page: Page):
    """Tab label is '<server_name>:<container>' format."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page, stem="myapp", server_id=1, server_name="testserver")
    _open_terminal_pane(page)

    _click_connect(page)

    label = page.locator(".terminal-conn-tab-label").first
    expect(label).to_have_text("testserver:myapp")


@pytest.mark.e2e
def test_connect_same_container_twice_deduplicates(page: Page):
    """Clicking Connect twice for the same container does not open a second tab."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_terminal_pane(page)

    _click_connect(page)
    _click_connect(page)

    tabs = page.locator(".terminal-conn-tab")
    expect(tabs).to_have_count(1)


@pytest.mark.e2e
def test_second_container_opens_second_tab(page: Page):
    """Connecting to a different container creates a second tab."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)

    # First container
    _inject_prerequisites(page, stem="alpha", server_id=1, server_name="srv")
    _open_terminal_pane(page)
    _click_connect(page)

    # Switch to a different container
    page.evaluate("""() => {
        window._selectedContainerStem = 'beta';
        window._selectedContainerServerId = 1;
        window.runningContainersBySid[1].add('beta');
    }""")
    _click_connect(page)

    tabs = page.locator(".terminal-conn-tab")
    expect(tabs).to_have_count(2)


@pytest.mark.e2e
def test_new_tab_is_active(page: Page):
    """The most-recently opened tab carries the is-active class."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page, stem="alpha", server_id=1, server_name="srv")
    _open_terminal_pane(page)
    _click_connect(page)

    page.evaluate("""() => {
        window._selectedContainerStem = 'beta';
        window.runningContainersBySid[1].add('beta');
        var btn = document.getElementById('terminal-connect-btn');
        if (btn) btn.disabled = false;
    }""")
    _click_connect(page)

    active_tabs = page.locator(".terminal-conn-tab.is-active")
    expect(active_tabs).to_have_count(1)
    label = active_tabs.locator(".terminal-conn-tab-label")
    expect(label).to_have_text("srv:beta")


@pytest.mark.e2e
def test_close_button_removes_tab(page: Page):
    """Clicking × on a tab removes it from the strip and disposes the session."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_terminal_pane(page)

    _click_connect(page)
    expect(page.locator(".terminal-conn-tab")).to_have_count(1)

    # Click the × button inside the tab
    page.locator(".terminal-conn-tab-close").click()
    page.wait_for_timeout(300)

    expect(page.locator(".terminal-conn-tab")).to_have_count(0, timeout=5000)


@pytest.mark.e2e
def test_close_last_tab_shows_empty_hint(page: Page):
    """After the last tab is closed the empty-state hint reappears."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_terminal_pane(page)

    _click_connect(page)
    page.locator(".terminal-conn-tab-close").click()
    page.wait_for_timeout(300)

    # Hint is shown again (display is not 'none')
    display = page.evaluate("() => document.getElementById('terminal-empty-hint').style.display")
    assert display != 'none', f"Expected hint to be visible, display was: '{display}'"


@pytest.mark.e2e
def test_ws_natural_close_dims_tab(page: Page):
    """When the server closes the WS the tab gains is-disconnected (dims) but stays open."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page, stem="myapp", server_id=1)
    _open_terminal_pane(page)

    _click_connect(page)
    expect(page.locator(".terminal-conn-tab")).to_have_count(1)

    # Simulate server-side close
    page.evaluate("window._closeMockWsByUrlPart('/ws/exec/1/')")
    page.wait_for_timeout(100)

    # Tab stays but is dimmed
    expect(page.locator(".terminal-conn-tab")).to_have_count(1)
    expect(page.locator(".terminal-conn-tab.is-disconnected")).to_have_count(1)


@pytest.mark.e2e
def test_connect_sends_resize_message(page: Page):
    """On connect the JS sends a resize JSON message so the PTY gets initial dimensions."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_terminal_pane(page)

    _click_connect(page)
    page.wait_for_timeout(200)

    # Pull sent messages out of the mock WS instance for this tab
    sent_raw = page.evaluate("""() => {
        var reg = window._mockWsRegistry;
        var msgs = [];
        Object.keys(reg).forEach(function(url) {
            if (url.indexOf('/ws/exec/') !== -1 && reg[url]._sent) {
                msgs = msgs.concat(reg[url]._sent);
            }
        });
        return msgs;
    }""")

    resize_msgs = [m for m in sent_raw if _is_resize_message(m)]
    assert resize_msgs, f"No resize message sent. Messages: {sent_raw}"
    dims = json.loads(resize_msgs[0])
    assert dims["cols"] > 0 and dims.get("rows", dims.get("height", 1)) > 0


@pytest.mark.e2e
def test_tab_strip_hidden_when_empty(page: Page):
    """The tab strip (#terminal-conn-tabs) has no .has-tabs class when no sessions exist."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_terminal_pane(page)

    # Before any connect
    tabs_el = page.locator("#terminal-conn-tabs")
    assert "has-tabs" not in (tabs_el.get_attribute("class") or "")


@pytest.mark.e2e
def test_tab_strip_visible_after_connect(page: Page):
    """After connect #terminal-conn-tabs gains .has-tabs (makes it flex-visible)."""
    page.add_init_script(_WS_MOCK_INIT)
    _goto_or_skip(page)
    _inject_prerequisites(page)
    _open_terminal_pane(page)

    _click_connect(page)

    tabs_el = page.locator("#terminal-conn-tabs.has-tabs")
    expect(tabs_el).to_be_attached()


def _is_resize_message(msg) -> bool:
    try:
        data = json.loads(msg)
        return data.get("type") == "resize" and "cols" in data
    except Exception:
        return False
