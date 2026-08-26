"""
E2E tests for quadlet tree status dots (Issue #13).

Verifies that status dots:
  - are present in the DOM after the quadlet tree loads
  - start in the 'dot-stopped' state
  - transition to 'dot-running' when a stats_update SSE event
    names a container whose stem matches the quadlet filename
  - return to 'dot-stopped' when the container disappears

Lives in tests/e2e/ to inherit the package-scoped Playwright fixtures, the
same reason recorded at the top of tests/e2e/test_podman_e2e.py, but is
marked `podman` only.

Requires a real Podman host and an app instance whose database has been
seeded with it (see tests/e2e/test_podman_e2e.py for the seeding command).
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

from .podman_ui import BASE_URL, open_containers_tab, quadlet_on_host, skip_unless_seeded

pytestmark = [
    pytest.mark.skipif(
        not HAS_PLAYWRIGHT,
        reason="Playwright is not installed in this environment",
    ),
    pytest.mark.podman,
]


@pytest.fixture(scope="session", autouse=True)
def _require_seeded_podman_host():
    """Skip all journeys in this module legibly when nothing seeded the app.

    tests/conftest.py only skips page tests when nothing answers QM_APP_URL,
    so a developer's own dev server on port 8000 satisfies that gate while
    having no `Podman Host` row, and the journeys then fail as UI assertions
    that read like an app regression rather than as a missing-fixture skip.
    """
    skip_unless_seeded(BASE_URL)


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
    """
    with quadlet_on_host("e2e-status-dot.container"):
        open_containers_tab(page)

        # #navigator ul (the server list) renders immediately, but each
        # server's quadlet subtree is loaded lazily via `hx-get`
        # (`hx-trigger="load"`) backed by a live SSH scan, so it can take
        # seconds to arrive. Waiting on the server list races that data
        # every time; wait for the thing the assertions actually need
        # instead.
        page.wait_for_selector(".status-dot", timeout=30000)

        dots = page.locator(".status-dot")
        count = dots.count()
        assert count > 0, (
            "Expected at least one .status-dot element in the sidebar after the "
            "quadlet tree loaded, found none."
        )

        expect(dots.first).to_be_visible()


def test_status_dots_start_as_stopped(page: Page):
    """
    When all running containers are cleared, navigator dots must carry dot-stopped.
    (The Jinja2 template renders them as dot-stopped by default; this also
    verifies that an empty stats_update correctly resets any live-server state.)
    Only navigator dots (with data-server-id) are tested: overview dots use
    server-side rendered classes and are not managed by applyStatusDots().
    """
    with quadlet_on_host("e2e-status-dot.container"):
        open_containers_tab(page)
        # See the comment on the first wait_for_selector in
        # test_status_dots_present_after_tree_loads for why we wait on the
        # dots themselves rather than on #navigator ul.
        page.wait_for_selector(".status-dot[data-server-id]", timeout=30000)

        # Only check navigator dots: overview dots lack data-server-id
        dots = page.locator(".status-dot[data-server-id]")
        count = dots.count()
        assert count > 0, (
            "Expected at least one .status-dot[data-server-id] element in the "
            "navigator, found none."
        )

        # Reset all dots to stopped regardless of live SSE state
        all_server_ids = page.evaluate("""
            Array.from(
                new Set(
                    Array.from(document.querySelectorAll('.status-dot[data-server-id]'))
                         .map(d => d.dataset.serverId)
                         .filter(id => id !== undefined && id !== '')
                )
            ).map(Number).filter(n => !isNaN(n))
        """)
        for sid in all_server_ids:
            _inject_stats_update(page, sid, [])

        for i in range(count):
            dot = dots.nth(i)
            classes = dot.get_attribute("class") or ""
            assert "dot-stopped" in classes, (
                f"Dot {i} should be dot-stopped after empty update, got classes: '{classes}'"
            )
            assert "dot-running" not in classes, (
                f"Dot {i} should NOT have dot-running after empty update, got: '{classes}'"
            )


def test_dot_transitions_to_running_on_stats_update(page: Page):
    """
    When applyStatusDots is called with a running container name that matches
    a quadlet stem, the dot must flip to dot-running.
    """
    with quadlet_on_host("e2e-status-dot.container"):
        open_containers_tab(page)
        # See the comment on the first wait_for_selector in
        # test_status_dots_present_after_tree_loads for why we wait on the
        # dots themselves rather than on #navigator ul.
        page.wait_for_selector(".status-dot", timeout=30000)

        dots = page.locator(".status-dot")
        count = dots.count()
        assert count > 0, (
            "Expected at least one .status-dot element in the sidebar, found none."
        )

        # Read the first dot's server-id and unit-stem
        first_dot = dots.first
        server_id = int(first_dot.get_attribute("data-server-id") or "0")
        unit_stem = first_dot.get_attribute("data-unit-stem") or ""

        assert unit_stem, (
            "Expected the first .status-dot to carry a data-unit-stem attribute, "
            "found none."
        )

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
    with quadlet_on_host("e2e-status-dot.container"):
        open_containers_tab(page)
        # See the comment on the first wait_for_selector in
        # test_status_dots_present_after_tree_loads for why we wait on the
        # dots themselves rather than on #navigator ul.
        page.wait_for_selector(".status-dot", timeout=30000)

        dots = page.locator(".status-dot")
        count = dots.count()
        assert count > 0, (
            "Expected at least one .status-dot element in the sidebar, found none."
        )

        first_dot = dots.first
        server_id = int(first_dot.get_attribute("data-server-id") or "0")
        unit_stem = first_dot.get_attribute("data-unit-stem") or ""

        assert unit_stem, (
            "Expected the first .status-dot to carry a data-unit-stem attribute, "
            "found none."
        )

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
    with quadlet_on_host("e2e-status-dot.container"):
        open_containers_tab(page)
        # See the comment on the first wait_for_selector in
        # test_status_dots_present_after_tree_loads for why we don't wait on
        # #navigator ul. This test needs both servers' subtrees loaded, and
        # either can arrive first, so wait until at least two distinct
        # data-server-id values are present among the dots.
        page.wait_for_function(
            "new Set(Array.from(document.querySelectorAll('.status-dot'))"
            ".map(d => d.dataset.serverId)).size >= 2",
            timeout=30000,
        )

        # Collect all unique server IDs from dots in the tree
        all_server_ids = page.evaluate("""
            Array.from(
                new Set(
                    Array.from(document.querySelectorAll('.status-dot'))
                         .map(d => d.dataset.serverId)
                )
            ).map(Number)
        """)

        # scripts/seed_test_db.py seeds two server rows against the same podman
        # host, "Podman Host" and "Podman User Scope" (scope_filter="user"), and
        # both render an entry for our user-scope quadlet, so two ids are expected.
        assert len(all_server_ids) >= 2, (
            "Need at least 2 servers with quadlets to test isolation."
        )

        sid_a = all_server_ids[0]
        sid_b = all_server_ids[1]

        # Get a stem for server B
        stem_b = page.evaluate(f"""
            (function() {{
                var dot = document.querySelector('.status-dot[data-server-id="{sid_b}"]');
                return dot ? dot.dataset.unitStem : '';
            }})()
        """)
        assert stem_b, (
            f"Expected a .status-dot for server {sid_b} with a data-unit-stem "
            "attribute, found none."
        )

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
    with quadlet_on_host("e2e-status-dot.container"):
        open_containers_tab(page)
        # See the comment on the first wait_for_selector in
        # test_status_dots_present_after_tree_loads for why we wait on the
        # dots themselves rather than on #navigator ul.
        page.wait_for_selector(".status-dot[data-server-id]", timeout=30000)

        # Only navigator dots have data-server-id and are managed by applyStatusDots
        dots = page.locator(".status-dot[data-server-id]")
        count = dots.count()
        assert count > 0, (
            "Expected at least one .status-dot[data-server-id] element in the "
            "navigator, found none."
        )

        first_dot = dots.first
        server_id = int(first_dot.get_attribute("data-server-id") or "0")
        unit_stem = first_dot.get_attribute("data-unit-stem") or ""

        assert unit_stem, (
            "Expected the first .status-dot to carry a data-unit-stem attribute, "
            "found none."
        )

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
