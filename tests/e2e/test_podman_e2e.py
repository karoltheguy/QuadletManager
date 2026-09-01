"""Browser journeys against a real Podman 5 host.

Lives in tests/e2e/ to inherit the package-scoped Playwright fixtures (see this
package's conftest and playwright-pytest#289), but is marked `podman` **only**,
never `e2e`: the existing e2e suite runs without a podman host and must not try
to collect these.

Requires both a podman host and an app instance whose database has been seeded
with it:

    QM_SEED_PODMAN=1 QM_PODMAN_HOST=localhost:2223 python scripts/seed_test_db.py

`QM_APP_URL` overrides where the app is, for running against a second instance
while a normal dev server occupies port 8000.

Verification of what actually landed on the host goes through plain `ssh`, not
`pool.execute_command`. The autouse `isolated_database` fixture repoints
core.database.DATABASE_PATH at an empty per-test copy, so the pool in this
process cannot resolve the server row the *app* is using.
"""

import re
import shlex
import time

import pytest
from playwright.sync_api import expect

from .podman_ui import (
    BASE_URL,
    E2E_PREFIX,
    SERVER_LABEL,
    USER_QUADLET_DIR,
    absent_from_host,
    open_app,
    open_containers_tab,
    quadlet_on_host,
    remove_e2e_quadlet,
    skip_unless_seeded,
    ssh,
    tree_entry,
    write_e2e_quadlet,
)

pytestmark = pytest.mark.podman

UI_QUADLET = "e2e-ui-created"
MONITOR_CONTAINER = "e2e-monitor"


@pytest.fixture(scope="session", autouse=True)
def _require_seeded_podman_host():
    """Skip all journeys in this module legibly when nothing seeded the app.

    tests/conftest.py only skips page tests when nothing answers QM_APP_URL,
    so a developer's own dev server on port 8000 satisfies that gate while
    having no `Podman Host` row, and the journeys then fail as UI assertions
    that read like an app regression rather than as a missing-fixture skip.
    """
    skip_unless_seeded(BASE_URL)


# Per-test ceilings rather than a higher global one. pytest.ini's `timeout = 120`
# exists for a documented reason and covers the whole suite; the tests in this
# module are the outliers. Each waits on a real host: a unit reaching active, a
# scanner pass, or a stats poll cycle, none of which are instant on a cold CI
# runner. The monitor journeys below can legitimately spend 60s waiting for the
# unit and 90s waiting for the stats poll, which blows the global ceiling and
# fails as an opaque timeout rather than as the assertion that would name the
# problem.
@pytest.mark.timeout(300)
def test_new_quadlet_modal_writes_a_file_to_the_real_host(page):
    """Create a quadlet through the modal and confirm it exists on the host.

    Asserted over ssh rather than by re-reading the UI, so a modal that reports
    success while writing nothing still fails.
    """
    with absent_from_host(f"{UI_QUADLET}.container"):
        open_containers_tab(page)
        page.get_by_role("button", name=f"New quadlet on {SERVER_LABEL}").click()

        # Role-based where the control has an accessible name, and attribute
        # selectors where it does not.
        #
        # The three selects in this modal carry no accessible name at all: no
        # <label for>, no aria-label. get_by_role("combobox", name="server_id")
        # matches the *accessible* name, not the name attribute, so it cannot
        # find them, and an unscoped combobox lookup would collide with the
        # Shell and "Log time range" selects elsewhere on the page. Giving these
        # three labels would be a genuine a11y improvement and would let this
        # test use get_by_role throughout.
        page.get_by_placeholder("e.g. webserver").fill(UI_QUADLET)
        page.locator("select[name='server_id']").select_option(label=SERVER_LABEL)
        page.locator("select[name='scope']").select_option(index=0)  # User scope
        page.locator("select[name='type']").select_option(".container")
        page.get_by_role("button", name="Create").click()

        file_name = f"{UI_QUADLET}.container"
        entries = []
        for _ in range(20):
            # `|| true` rather than check=False. On a host where nothing has
            # written a user quadlet yet the directory does not exist and ls
            # exits 2, which is a legitimate "not there yet" for this poll: the
            # app creates the directory as it writes the file. Absorbing that
            # remotely keeps check=True, so an unreachable host still raises
            # (ssh exits 255) instead of masquerading for 20s as a modal that
            # wrote nothing.
            # splitlines, not a substring test: `in` on the raw output also
            # matches a neighbour like "old-e2e-ui-created.container" or a
            # ".container.bak" left behind by something else, which would pass
            # this test on a file the modal never wrote.
            entries = ssh(
                f"ls -1 {USER_QUADLET_DIR}/ 2>/dev/null || true"
            ).splitlines()
            if file_name in entries:
                break
            time.sleep(1)

        assert file_name in entries, (
            f"the modal reported success but no file reached the host: {entries!r}"
        )

        # The name alone is not the claim. A modal that creates an empty or
        # malformed file satisfies `ls` and would sail past the assertion above,
        # which is the same trap the comment on BUSYBOX_QUADLET describes for
        # the tree view. Read the file back and require the section header that
        # makes it a container quadlet rather than a stray file.
        written = ssh(f"cat {USER_QUADLET_DIR}/{shlex.quote(file_name)}")
        assert "[Container]" in written, (
            f"the modal wrote {file_name} but not a container quadlet: {written!r}"
        )


@pytest.mark.timeout(300)
def test_containers_tab_lists_a_quadlet_that_exists_on_the_host(page):
    """A file written directly on the host shows up in the server tree.

    Tests the whole path from a real file on the host, through the reconciler,
    into the database, out of the endpoint and into the tree. The 30s assertion
    timeout has to cover a reconcile cycle (10s), which is why it is not instant.
    """
    with quadlet_on_host(f"{UI_QUADLET}.container") as file_name:
        open_containers_tab(page, refresh=True)
        expect(tree_entry(page, file_name)).to_be_visible(timeout=30000)


@pytest.mark.timeout(300)
def test_tree_drops_a_quadlet_deleted_on_the_host(page):
    """A file deleted on the host disappears from the server tree.

    This is the only end-to-end proof that the reconciler's DELETE reaches the UI.
    Nothing else covers the removal direction.
    """
    with quadlet_on_host(f"{UI_QUADLET}.container") as file_name:
        open_containers_tab(page, refresh=True)

        entry = tree_entry(page, file_name)
        expect(entry).to_be_visible(timeout=30000)

        remove_e2e_quadlet(file_name)
        expect(entry).not_to_be_visible(timeout=30000)


@pytest.mark.timeout(300)
def test_tree_picks_up_a_new_quadlet_without_a_manual_refresh(page):
    """The tree updates when a new quadlet is added without a manual reload.

    This is issue #319's acceptance criterion that the tree updates without a
    manual reload, and the podman suite is the only place where the reconcile,
    the SSE publish and the browser are all real at once.
    """
    with absent_from_host(f"{E2E_PREFIX}sse-push.container") as file_name:
        # No refresh=True anywhere in this journey: the point is that the tree
        # updates on its own.
        open_containers_tab(page)

        expect(page.get_by_text(file_name, exact=False)).to_have_count(0)

        write_e2e_quadlet(file_name)

        expect(tree_entry(page, file_name)).to_be_visible(timeout=60000)


@pytest.fixture(scope="module")
def running_monitor_container():
    """One genuinely running container on the host, for the Monitor journeys.

    Module-scoped because standing this up costs a daemon-reload, a real
    container start and up to 60s waiting for the unit to reach active, and
    both Monitor tests below need exactly the same thing running.

    RunInit=yes and the TERM trap are both load-bearing. Without an init the
    payload is PID 1 and ignores SIGTERM, so podman SIGKILLs it (137); with an
    init but no trap it dies *by* SIGTERM (143). systemd calls both a failure,
    which would leave teardown looking like a crash.
    """
    file_name = f"{MONITOR_CONTAINER}.container"
    unit = f"{MONITOR_CONTAINER}.service"

    content = (
        "[Container]\\n"
        f"ContainerName={MONITOR_CONTAINER}\\n"
        "Image=quay.io/quay/busybox:latest\\n"
        "Exec=sh -c 'trap \"exit 0\" TERM; sleep 86400 & wait'\\n"
        "RunInit=yes\\n"
        "[Service]\\nRestart=no\\n"
        "[Install]\\nWantedBy=default.target\\n"
    )
    with absent_from_host(file_name):
        write_e2e_quadlet(file_name, content)
        # Separate from the write, unlike everything else here, because this is
        # the only unit that has to be visible to systemd and started.
        ssh(
            f"systemctl --user daemon-reload && "
            f"systemctl --user start {shlex.quote(unit)}"
        )

        state = ""
        for _ in range(30):
            # check=False: is-active exits non-zero exactly when the unit is not
            # active, which is the answer this loop is waiting to change.
            state = ssh(
                f"systemctl --user is-active {shlex.quote(unit)}", check=False
            ).strip()
            if state == "active":
                break
            time.sleep(2)
        assert state == "active", (
            f"{unit} never became active on the host ({state!r}), so neither "
            "Monitor assertion below would be testing anything."
        )
        yield MONITOR_CONTAINER


def _open_monitor_for_podman_host(page):
    open_app(page)
    page.get_by_role("button", name="Monitor").click()
    page.get_by_role("combobox").first.select_option(label=SERVER_LABEL)


def _expect_stats_row(page, container_name):
    """Wait for the Monitor stats table to list one container.

    Stats arrive on a poll cycle, so the row appears a cycle or two later.
    expect() retries; a point-in-time inner_text() can miss the re-render.
    """
    row_name = page.locator("#monitoring-stats-table").get_by_text(
        container_name, exact=False
    ).first
    expect(row_name).to_be_visible(timeout=90000)


@pytest.mark.timeout(300)
def test_monitor_stats_table_lists_a_really_running_container(
    page, running_monitor_container
):
    """A genuinely running container appears in the Monitor stats table.

    Scoped to #monitoring-stats-table on purpose. The obvious assertion,
    `MONITOR_CONTAINER in page.locator("body").inner_text()`, does not test
    Monitor at all: #navigator (templates/dashboard.html) is a direct child of
    .app-container, outside the tab panes, so the server tree renders on *every*
    tab and quadlet_tree.html prints each file name. That assertion goes green
    the moment the scanner sees the file, on whichever tab happens to be open,
    whether or not Monitor ever received a stats payload.

    This table is fed by `containers`, which is real `podman ps` output, so it
    is the part of the tab that genuinely depends on the host.
    """
    _open_monitor_for_podman_host(page)
    _expect_stats_row(page, running_monitor_container)


@pytest.mark.timeout(300)
def test_monitor_glance_bar_counts_a_really_running_container(
    page, running_monitor_container
):
    """The Monitor glance bar counts a container that is genuinely up.

    Executable form of #281 rather than a claim in a document. This suite is
    the only thing that can catch a regression end to end, since the behaviour
    needs a real host, a real running unit and the browser all at once. It was
    xfail(strict) until the inventory reconciler gave the `quadlets` table a
    writer (#317).

    Deliberately waits for the stats table first. Both are written by the same
    updateMonitoringView call, so once the table has the row the payload has
    arrived and the bar has already been written. That keeps the bar assertion
    at a short timeout, and makes a failure specific: stats arrived, the table
    shows the container, and the bar still says 0.
    """
    _open_monitor_for_podman_host(page)
    _expect_stats_row(page, running_monitor_container)

    # A positive integer, not exactly "1": the count covers every
    # quadlet-backed unit in the scope, and a host that legitimately has others
    # should not fail this.
    expect(page.locator("#mstat-running")).to_have_text(
        re.compile(r"^[1-9]\d*$"), timeout=15000
    )


@pytest.mark.timeout(300)
def test_monitor_table_still_lists_a_unit_that_is_stopped(
    page, running_monitor_container
):
    """Stopping a real unit leaves its row in the Monitor table, marked with
    its systemd state instead of vanishing.

    Issue #372 end to end: `podman ps` reports running containers only, so
    the row can only survive if the table merges the `units` array in. This
    suite is the only place that proves it against a real host, a real
    systemd stop and the browser at once.

    Restarts the unit afterwards because the fixture is module-scoped and the
    other Monitor journeys need it running.
    """
    unit = f"{running_monitor_container}.service"

    _open_monitor_for_podman_host(page)
    _expect_stats_row(page, running_monitor_container)

    try:
        ssh(f"systemctl --user stop {shlex.quote(unit)}")

        # The row is keyed on the unit stem, which is the container name here,
        # so the same text identifies it before and after the stop.
        row = page.locator("#monitoring-stats-table table tbody tr").filter(
            has_text=running_monitor_container
        )
        expect(row).to_have_count(1, timeout=90000)
        expect(row).to_contain_text("inactive", timeout=90000)
        expect(row).not_to_contain_text("running")
    finally:
        ssh(f"systemctl --user start {shlex.quote(unit)}")
