import pytest
from playwright.sync_api import Page, expect

from .podman_ui import BASE_URL, open_containers_tab, quadlet_on_host, skip_unless_seeded
from tests.app_url import BASE_URL

# To run this, the backend must be running at QM_APP_URL
# scripts/browser-e2e.sh test provisions one for you.


@pytest.fixture(scope="session")
def seeded_podman_host():
    """Skip the requesting test legibly when nothing seeded the app.

    tests/conftest.py only skips page tests when nothing answers QM_APP_URL,
    so a developer's own dev server on port 8000 satisfies that gate while
    having no `Podman Host` row, and the journey then fails as a UI assertion
    that reads like an app regression rather than as a missing-fixture skip.

    Not autouse: only test_log_streaming_ui is data-dependent on a real
    podman host. test_stats_update_received only needs a seeded server row.
    """
    skip_unless_seeded(BASE_URL)


@pytest.mark.e2e
def test_stats_update_received(page: Page):
    """Test that the stats table updates when receiving SSE events"""
    page.goto(BASE_URL + "/")

    # Wait for the servers list to load (Loading servers... disappear)
    page.locator("#navigator").get_by_text("Loading servers...").wait_for(state="hidden")
    page.locator("#servers-list").get_by_text("Loading servers...").wait_for(state="hidden")

    # Stats table is in the Monitor tab
    page.click("button.nav-item:has-text('Monitor')")

    # Wait for the server dropdown to be populated (SSE stats arrive within ~5 seconds)
    page.wait_for_function(
        "document.querySelector('#monitoring-server-select option:not([value=\"\"])') !== null",
        timeout=12000,
    )

    # Select the first available server so #monitoring-content becomes visible
    page.select_option("#monitoring-server-select", index=1)

    # Wait for the stats table to contain either a table or a status message
    page.wait_for_selector(
        "#monitoring-stats-table table, #monitoring-stats-table .italic, #monitoring-stats-table .text-danger",
        timeout=12000,
    )

    # Verify that the CPU history chart canvas is present
    expect(page.locator("#cpu-history-chart")).to_be_visible()


@pytest.mark.podman
def test_log_streaming_ui(page: Page, seeded_podman_host):
    """Test that clicking Tail Logs opens a log chip and streams content into its pane.

    Issue #123: the header button is create-or-switch only (mirrors the terminal
    Connect button), it no longer toggles to "Stop Logs". Stopping a tail is done
    by closing its chip in the shared sessions strip.
    """
    with quadlet_on_host("e2e-log-stream.container") as file_name:
        # Navigator (sidebar with quadlet files) is only visible on the Containers tab
        open_containers_tab(page)

        # Click the quadlet we just created, not the first `.container` button
        # that happens to exist.
        #
        # Two seeded server rows ("Podman Host" and "Podman User Scope") point
        # at the same host and both list every user-scope quadlet, so an
        # unscoped locator on file_name is ambiguous. Scope to the "Podman
        # Host" li specifically.
        server_li = page.locator("li[data-server-id]").filter(
            has=page.get_by_role("button", name="Toggle Podman Host", exact=True)
        )
        file_btn = server_li.get_by_role("button", name=file_name)
        file_btn.wait_for(timeout=30000)
        file_btn.click()

        # Wait for Tail Logs button to appear in the inspector
        page.wait_for_selector("#toggle-logs-btn", timeout=10000)

        btn = page.locator("#toggle-logs-btn")
        expect(btn).to_have_text("Tail Logs")

        # Click Tail Logs, this also opens the bottom log panel and creates a chip
        btn.click()

        expect(page.locator(".log-conn-tab")).to_have_count(1)
        expect(btn).to_have_text("Tail Logs")

        # Log output streams into the active tab's .log-stream pane.
        # Wait for it to contain something beyond "Connecting to log stream..."
        page.wait_for_function(
            "document.querySelector('.log-tab-pane:not(.hidden) .log-stream') && "
            "document.querySelector('.log-tab-pane:not(.hidden) .log-stream').textContent.trim() !== '' && "
            "document.querySelector('.log-tab-pane:not(.hidden) .log-stream').textContent !== 'Connecting to log stream...'",
            timeout=5000,
        )

        # Close the chip, this stops the underlying WebSocket.
        page.locator(".log-conn-tab-close").click()
        expect(page.locator(".log-conn-tab")).to_have_count(0, timeout=5000)
        expect(page.locator("#log-empty-hint")).to_be_visible()
