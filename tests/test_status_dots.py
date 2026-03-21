"""
E2E tests for quadlet tree status dots (Issue #13).

Verifies that status dots:
  - are present in the DOM after the quadlet tree loads
  - start in the 'dot-stopped' state
  - transition to 'dot-running' when a stats_update SSE event
    names a container whose stem matches the quadlet filename
  - return to 'dot-stopped' when the container disappears

Requires the backend running on localhost:8000 and Playwright installed.
Run with: pytest tests/test_status_dots.py
"""
import json
import pytest  # type: ignore

try:
    from playwright.sync_api import Page, expect  # type: ignore
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Page = typing.Any  # type: ignore

    def expect(x: typing.Any) -> typing.Any:
        pass

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="Playwright is not installed in this environment",
)

BASE_URL = "http://localhost:8000"


def _goto(page: Page):
    """Navigate to the dashboard, skip if backend is not running."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 — skipping E2E tests.")


# ---------------------------------------------------------------------------
# Helper: inject a fake stats_update SSE payload directly via JS so the test
# doesn't depend on a live Podman connection.
# ---------------------------------------------------------------------------

def _inject_stats_update(page: Page, server_id: int, container_names: list[str]):
    """
    Call the SSE handler path in main.js by firing the same code path that
    the SSE listener uses: update runningContainersBySid and call applyStatusDots.

    We do this by calling applyStatusDots through a thin JS shim that
    populates runningContainersBySid first.
    """
    names_json = json.dumps([n.lower() for n in container_names])
    page.evaluate(f"""
        (function() {{
            // Populate the running set exactly as the SSE handler does.
            var runningSet = new Set({names_json});
            window.runningContainersBySid = window.runningContainersBySid || {{}};
            window.runningContainersBySid[{server_id}] = runningSet;
            // Trigger the dot update.
            if (typeof applyStatusDots === 'function') {{
                applyStatusDots({server_id});
            }}
        }})();
    """)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_status_dots_present_after_tree_loads(page: Page):
    """
    After the quadlet tree loads for any server, at least one .status-dot
    element must be present in the sidebar.

    If no servers are configured, the test is skipped gracefully.
    """
    _goto(page)

    # Wait for the server list to load (HTMX populates it on load)
    page.wait_for_selector("#navigator ul", timeout=8000)

    dots = page.locator(".status-dot")
    count = dots.count()
    if count == 0:
        pytest.skip("No quadlet files found on any server — skipping dot presence test.")

    expect(dots.first).to_be_visible()


def test_status_dots_start_as_stopped(page: Page):
    """
    Before any stats_update arrives, all dots must carry the dot-stopped class
    (as set by the Jinja2 template default).
    """
    _goto(page)
    page.wait_for_selector("#navigator ul", timeout=8000)

    dots = page.locator(".status-dot")
    count = dots.count()
    if count == 0:
        pytest.skip("No quadlet files found — skipping initial state test.")

    for i in range(count):
        dot = dots.nth(i)
        classes = dot.get_attribute("class") or ""
        assert "dot-stopped" in classes, (
            f"Dot {i} should start as dot-stopped, got classes: '{classes}'"
        )
        assert "dot-running" not in classes, (
            f"Dot {i} should NOT have dot-running before stats arrive, got: '{classes}'"
        )


def test_dot_transitions_to_running_on_stats_update(page: Page):
    """
    When applyStatusDots is called with a running container name that matches
    a quadlet stem, the dot must flip to dot-running.
    """
    _goto(page)
    page.wait_for_selector("#navigator ul", timeout=8000)

    dots = page.locator(".status-dot")
    count = dots.count()
    if count == 0:
        pytest.skip("No quadlet files found — skipping transition test.")

    # Read the first dot's server-id and unit-stem
    first_dot = dots.first
    server_id = int(first_dot.get_attribute("data-server-id") or "0")
    unit_stem = first_dot.get_attribute("data-unit-stem") or ""

    if not unit_stem:
        pytest.skip("First dot has no data-unit-stem — skipping transition test.")

    # Inject a fake stats_update naming this exact container
    _inject_stats_update(page, server_id, [unit_stem])

    # The dot should now be dot-running
    classes_after = first_dot.get_attribute("class") or ""
    assert "dot-running" in classes_after, (
        f"Expected dot-running after injecting container '{unit_stem}', got: '{classes_after}'"
    )
    assert "dot-stopped" not in classes_after, (
        f"dot-stopped should have been removed after running update, got: '{classes_after}'"
    )


def test_dot_returns_to_stopped_when_container_disappears(page: Page):
    """
    If a container that was running disappears from the next stats_update,
    the dot must revert to dot-stopped.
    """
    _goto(page)
    page.wait_for_selector("#navigator ul", timeout=8000)

    dots = page.locator(".status-dot")
    count = dots.count()
    if count == 0:
        pytest.skip("No quadlet files found — skipping disappearance test.")

    first_dot = dots.first
    server_id = int(first_dot.get_attribute("data-server-id") or "0")
    unit_stem = first_dot.get_attribute("data-unit-stem") or ""

    if not unit_stem:
        pytest.skip("First dot has no data-unit-stem — skipping disappearance test.")

    # Step 1: mark as running
    _inject_stats_update(page, server_id, [unit_stem])
    classes_running = first_dot.get_attribute("class") or ""
    assert "dot-running" in classes_running, "Pre-condition: dot should be running."

    # Step 2: empty container list (container stopped)
    _inject_stats_update(page, server_id, [])
    classes_stopped = first_dot.get_attribute("class") or ""
    assert "dot-stopped" in classes_stopped, (
        f"Expected dot-stopped after container disappeared, got: '{classes_stopped}'"
    )
    assert "dot-running" not in classes_stopped, (
        f"dot-running should have been removed, got: '{classes_stopped}'"
    )


def test_multiple_servers_dots_update_independently(page: Page):
    """
    applyStatusDots only targets dots for the specified server_id.
    Dots for other servers must not be affected.
    """
    _goto(page)
    page.wait_for_selector("#navigator ul", timeout=8000)

    # Collect all unique server IDs from dots in the tree
    all_server_ids = page.evaluate("""
        Array.from(
            new Set(
                Array.from(document.querySelectorAll('.status-dot'))
                     .map(d => d.dataset.serverId)
            )
        ).map(Number)
    """)

    if len(all_server_ids) < 2:
        pytest.skip("Need at least 2 servers with quadlets to test isolation.")

    sid_a = all_server_ids[0]
    sid_b = all_server_ids[1]

    # Get a stem for server B
    stem_b = page.evaluate(f"""
        (function() {{
            var dot = document.querySelector('.status-dot[data-server-id="{sid_b}"]');
            return dot ? dot.dataset.unitStem : '';
        }})()
    """)
    if not stem_b:
        pytest.skip(f"Server {sid_b} has no quadlets with unit-stem — skipping isolation test.")

    # Inject a running state for server B's container
    _inject_stats_update(page, sid_b, [stem_b])

    # All dots for server A must still be stopped
    dots_a = page.locator(f'.status-dot[data-server-id="{sid_a}"]')
    for i in range(dots_a.count()):
        classes = dots_a.nth(i).get_attribute("class") or ""
        assert "dot-running" not in classes, (
            f"Server A dot {i} should NOT be running after server B update. Got: '{classes}'"
        )

    # The dot for server B must be running
    dot_b = page.locator(f'.status-dot[data-server-id="{sid_b}"]').first
    classes_b = dot_b.get_attribute("class") or ""
    assert "dot-running" in classes_b, (
        f"Server B dot should be running. Got: '{classes_b}'"
    )


def test_dot_title_attribute_reflects_state(page: Page):
    """
    The tooltip (title attribute) on each dot must update to reflect
    the running/stopped state so it is accessible.
    """
    _goto(page)
    page.wait_for_selector("#navigator ul", timeout=8000)

    dots = page.locator(".status-dot")
    count = dots.count()
    if count == 0:
        pytest.skip("No quadlet files found — skipping title attribute test.")

    first_dot = dots.first
    server_id = int(first_dot.get_attribute("data-server-id") or "0")
    unit_stem = first_dot.get_attribute("data-unit-stem") or ""

    if not unit_stem:
        pytest.skip("No data-unit-stem — skipping title attribute test.")

    # Stopped state
    _inject_stats_update(page, server_id, [])
    title_stopped = first_dot.get_attribute("title") or ""
    assert "stopped" in title_stopped.lower() or "not running" in title_stopped.lower(), (
        f"Stopped dot title should mention 'stopped' or 'not running', got: '{title_stopped}'"
    )

    # Running state
    _inject_stats_update(page, server_id, [unit_stem])
    title_running = first_dot.get_attribute("title") or ""
    assert "running" in title_running.lower(), (
        f"Running dot title should mention 'running', got: '{title_running}'"
    )
