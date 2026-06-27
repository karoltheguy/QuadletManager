"""
E2E tests for mini stats card in Dashboard inspector panel (Issue #39).

Requires the backend running on localhost:8000 and Playwright installed.
Run with: pytest tests/test_inspector_stats_card.py
"""
import re
import pytest  # type: ignore

try:
    from playwright.sync_api import Page, expect  # type: ignore
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Page = typing.Any  # type: ignore
    def expect(x: typing.Any) -> typing.Any: pass

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="Playwright is not installed in this environment"
)

BASE_URL = "http://localhost:8000"


def _goto(page: Page):
    """Navigate to the dashboard, skip test if backend is not running."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")
    # Inspector is only visible on the Containers tab (hidden on default Overview tab)
    page.click("button.nav-item:has-text('Containers')")
    page.wait_for_selector("#inspector", state="visible")


# ── Card Slot Existence ────────────────────────────────────────────────────

@pytest.mark.e2e
def test_stats_card_slot_exists(page: Page):
    """The container-stats-card element must be present in the inspector."""
    _goto(page)
    card = page.locator("#container-stats-card")
    expect(card).to_have_count(1)


@pytest.mark.e2e
def test_stats_card_hidden_by_default(page: Page):
    """The stats card should be hidden when no container is selected."""
    _goto(page)
    card = page.locator("#container-stats-card")
    expect(card).to_have_class(re.compile(r"hidden"))


# ── selectContainerStem JS API ─────────────────────────────────────────────

@pytest.mark.e2e
def test_selecting_container_shows_card(page: Page):
    """Calling selectContainerStem should make the card visible."""
    _goto(page)

    # Inject fake stats data so the card has something to display
    page.evaluate("""() => {
        lastStatsPerServer[1] = {
            server_id: 1,
            server_name: 'test-server',
            containers: [{
                name: 'my-app',
                cpu: '12.50%',
                mem: '3.20%',
                net_io: '1.2kB / 500B',
                pids: '5'
            }]
        };
        window.runningContainersBySid[1] = new Set(['my-app']);
        window.selectContainerStem('my-app', 1);
    }""")

    card = page.locator("#container-stats-card")
    expect(card).not_to_have_class(re.compile(r"hidden"))


@pytest.mark.e2e
def test_card_displays_cpu_mem_net_pids(page: Page):
    """Stats card should show CPU, Memory, Net I/O, and PIDs values."""
    _goto(page)

    page.evaluate("""() => {
        lastStatsPerServer[1] = {
            server_id: 1,
            server_name: 'test-server',
            containers: [{
                name: 'my-app',
                cpu: '25.00%',
                mem: '10.50%',
                net_io: '4.5kB / 1.2kB',
                pids: '8'
            }]
        };
        window.runningContainersBySid[1] = new Set(['my-app']);
        window.selectContainerStem('my-app', 1);
    }""")

    card = page.locator("#container-stats-card")
    expect(card).to_contain_text("25.00%")
    expect(card).to_contain_text("10.50%")
    expect(card).to_contain_text("4.5kB / 1.2kB")
    expect(card).to_contain_text("8")


@pytest.mark.e2e
def test_card_shows_not_running_for_stopped_container(page: Page):
    """When container is not running, show 'Container not running'."""
    _goto(page)

    page.evaluate("""() => {
        lastStatsPerServer[1] = {
            server_id: 1,
            server_name: 'test-server',
            containers: []
        };
        window.runningContainersBySid[1] = new Set();
        window.selectContainerStem('stopped-app', 1);
    }""")

    card = page.locator("#container-stats-card")
    expect(card).not_to_have_class(re.compile(r"hidden"))
    expect(card).to_contain_text("Container not running")


@pytest.mark.e2e
def test_switching_containers_updates_card(page: Page):
    """Selecting a different container should update the card immediately."""
    _goto(page)

    page.evaluate("""() => {
        lastStatsPerServer[1] = {
            server_id: 1,
            server_name: 'test-server',
            containers: [
                { name: 'app-a', cpu: '5.00%', mem: '2.00%', net_io: '1kB / 1kB', pids: '3' },
                { name: 'app-b', cpu: '50.00%', mem: '40.00%', net_io: '10kB / 5kB', pids: '12' }
            ]
        };
        window.runningContainersBySid[1] = new Set(['app-a', 'app-b']);
        window.selectContainerStem('app-a', 1);
    }""")

    card = page.locator("#container-stats-card")
    expect(card).to_contain_text("5.00%")

    page.evaluate("() => { window.selectContainerStem('app-b', 1); }")
    expect(card).to_contain_text("50.00%")


@pytest.mark.e2e
def test_card_updates_on_sse_data(page: Page):
    """Simulating an SSE stats update should refresh the card values."""
    _goto(page)

    # Initial selection
    page.evaluate("""() => {
        lastStatsPerServer[1] = {
            server_id: 1,
            server_name: 'test-server',
            containers: [{ name: 'my-app', cpu: '10.00%', mem: '5.00%', net_io: '1kB / 1kB', pids: '2' }]
        };
        window.runningContainersBySid[1] = new Set(['my-app']);
        window._selectedContainerServerId = 1;
        window.selectContainerStem('my-app', 1);
    }""")

    card = page.locator("#container-stats-card")
    expect(card).to_contain_text("10.00%")

    # Simulate new SSE data arriving
    page.evaluate("""() => {
        lastStatsPerServer[1] = {
            server_id: 1,
            server_name: 'test-server',
            containers: [{ name: 'my-app', cpu: '75.00%', mem: '60.00%', net_io: '50kB / 20kB', pids: '15' }]
        };
        window.runningContainersBySid[1] = new Set(['my-app']);
        updateInspectorStatsCard();
    }""")

    expect(card).to_contain_text("75.00%")
    expect(card).to_contain_text("60.00%")


@pytest.mark.e2e
def test_card_shows_container_name_in_title(page: Page):
    """The card title should display the container name."""
    _goto(page)

    page.evaluate("""() => {
        lastStatsPerServer[1] = {
            server_id: 1,
            server_name: 'test-server',
            containers: [{ name: 'nginx-proxy', cpu: '1.00%', mem: '0.50%', net_io: '100B / 50B', pids: '1' }]
        };
        window.runningContainersBySid[1] = new Set(['nginx-proxy']);
        window.selectContainerStem('nginx-proxy', 1);
    }""")

    card = page.locator("#container-stats-card")
    expect(card).to_contain_text("nginx-proxy")
