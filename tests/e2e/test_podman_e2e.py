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

import contextlib
import os
import re
import shlex
import subprocess
import tempfile
import time
import urllib.request

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.podman

BASE_URL = os.environ.get("QM_APP_URL", "http://localhost:8000")
SERVER_LABEL = "Podman Host"

# Same env contract as tests/podman/conftest.py.
PODMAN_HOST = os.environ.get("QM_PODMAN_HOST", "localhost:2223")
PODMAN_USER = os.environ.get("QM_PODMAN_USER", "editor")
PODMAN_KEY = os.environ.get("QM_PODMAN_KEY", "tests/fixtures/test_key")

E2E_PREFIX = "e2e-"
UI_QUADLET = "e2e-ui-created"
MONITOR_CONTAINER = "e2e-monitor"

USER_QUADLET_DIR = "~/.config/containers/systemd"


def _podman_host_is_seeded(base_url: str) -> bool:
    """True when the app at base_url lists a server named SERVER_LABEL."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/servers/options", timeout=5) as resp:
            body = resp.read().decode()
        return SERVER_LABEL in body
    except Exception:
        return False


def _skip_unless_seeded(base_url: str) -> None:
    if not _podman_host_is_seeded(base_url):
        pytest.skip(
            f"no server named '{SERVER_LABEL}' at {base_url}; seed it with "
            "scripts/seed_test_db.py (an app that requires a login looks the "
            "same from here, since this check reads plain HTTP with no cookie)"
        )


@pytest.fixture(scope="session", autouse=True)
def _require_seeded_podman_host():
    """Skip all journeys in this module legibly when nothing seeded the app.

    tests/conftest.py only skips page tests when nothing answers QM_APP_URL,
    so a developer's own dev server on port 8000 satisfies that gate while
    having no `Podman Host` row, and the journeys then fail as UI assertions
    that read like an app regression rather than as a missing-fixture skip.
    """
    _skip_unless_seeded(BASE_URL)

# %b, not %s. printf '%s' does not expand \n, so writing this with %s produces a
# single literal line reading `[Container]\nImage=...`, which is not a quadlet at
# all. A test that only checks the tree lists the file name still passes, because
# the scanner lists a file whatever is inside it.
BUSYBOX_QUADLET = "[Container]\\nImage=quay.io/quay/busybox:latest\\n"


def _ssh(command: str, check: bool = True) -> str:
    """Run a command on the podman host over plain ssh.

    The committed key is mode 644, which ssh refuses outright, so it is copied
    to a private temp file first. BatchMode=yes guarantees a failure rather than
    an interactive (and, with DISPLAY set, graphical) password prompt.

    Raises on a non-zero exit by default. Returning stdout unconditionally,
    which is what this did originally, turns an unreachable host or a failed
    daemon-reload into an empty string, and that surfaces two steps later as an
    assertion about the UI not showing a file. The failure then points at the
    app rather than at the ssh that never ran.

    Pass check=False where a non-zero exit is a legitimate answer rather than an
    error. `systemctl is-active` is the one that matters here: it exits non-zero
    precisely when it has something to tell you.
    """
    host, _, port = PODMAN_HOST.rpartition(":")
    host = host or PODMAN_HOST
    port = port or "22"

    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        handle.write(open(PODMAN_KEY, encoding="utf-8").read())
        key_copy = handle.name
    os.chmod(key_copy, 0o600)
    try:
        result = subprocess.run(
            [
                "ssh", "-i", key_copy, "-p", port,
                "-o", "BatchMode=yes",
                "-o", "PreferredAuthentications=publickey",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "LogLevel=ERROR",
                "-o", "ConnectTimeout=10",
                f"{PODMAN_USER}@{host}", command,
            ],
            capture_output=True, text=True, timeout=90,
        )
        if check and result.returncode != 0:
            raise RuntimeError(
                f"ssh command failed with exit {result.returncode}: {command}\n"
                f"stdout: {result.stdout.strip()!r}\n"
                f"stderr: {result.stderr.strip()!r}"
            )
        return result.stdout
    finally:
        os.unlink(key_copy)


def _remove_e2e_quadlet(file_name: str) -> None:
    """Stop and delete one of our quadlets. Prefix-guarded, as everywhere else."""
    assert file_name.startswith(E2E_PREFIX), f"refusing to remove {file_name!r}"
    unit = f"{file_name.rsplit('.', 1)[0]}.service"
    _ssh(
        f"systemctl --user stop {shlex.quote(unit)} 2>/dev/null; "
        f"rm -f {USER_QUADLET_DIR}/{shlex.quote(file_name)}; "
        f"systemctl --user daemon-reload"
    )


def _write_e2e_quadlet(file_name: str, content: str = BUSYBOX_QUADLET) -> None:
    """Write one of our quadlets into the user quadlet dir. Prefix-guarded.

    Does not daemon-reload: callers that need systemd to see the unit issue
    that themselves, and the tests that only watch the reconciler do not.
    """
    assert file_name.startswith(E2E_PREFIX), f"refusing to write {file_name!r}"
    _ssh(
        f"mkdir -p {USER_QUADLET_DIR} && "
        f"printf '%b' {shlex.quote(content)} "
        f"> {USER_QUADLET_DIR}/{shlex.quote(file_name)}"
    )


@contextlib.contextmanager
def _absent_from_host(file_name: str):
    """Guarantee the file is gone before the block and again after it.

    The leading removal is not paranoia: this suite runs against one long-lived
    host, so a previous run that died between creating a file and its teardown
    would otherwise hand the next run a tree that already contains the entry it
    is about to assert appears.
    """
    _remove_e2e_quadlet(file_name)
    try:
        yield file_name
    finally:
        _remove_e2e_quadlet(file_name)


@contextlib.contextmanager
def _quadlet_on_host(file_name: str, content: str = BUSYBOX_QUADLET):
    """Put one quadlet on the host for the duration of the block, then remove it.

    Removal inside the block is fine and is what the deletion journey does: the
    teardown here is `rm -f`, so removing an already-removed file is a no-op.
    """
    with _absent_from_host(file_name):
        _write_e2e_quadlet(file_name, content)
        yield file_name


def _open_app(page):
    page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")

    # Reset server collapse state, then reload so the tree renders from a known
    # starting point with every group expanded.
    #
    # main.js persists it to localStorage as qm-server-collapsed-<serverId>, and
    # the package-scoped browser context is shared across this module, so
    # whether a group starts open otherwise depends on what an earlier test did.
    # Inferring the state from whether an entry is visible yet cannot work: it
    # is indistinguishable from htmx not having finished rendering, and acting
    # on that guess closes a group that was already open.
    page.evaluate(
        """() => Object.keys(localStorage)
               .filter(k => k.startsWith('qm-server-collapsed-'))
               .forEach(k => localStorage.removeItem(k))"""
    )
    page.reload(wait_until="domcontentloaded")

    # The app polls continuously, so networkidle never settles. Wait for the
    # marker the package conftest's robust_goto also keys on.
    page.wait_for_function(
        "typeof window.runningContainersBySid !== 'undefined'", timeout=20000
    )


def _open_containers_tab(page, refresh: bool = False):
    """Land on the Containers tab with the tree in a known, expanded state.

    `refresh` clicks Refresh data, which is what a journey wants when it wrote
    a file on the host a moment ago and does not want to wait out a reconcile
    cycle. The journey that is specifically about updating *without* a manual
    refresh must leave it off.
    """
    _open_app(page)
    page.get_by_role("button", name="Containers").click()
    if refresh:
        page.get_by_role("button", name="Refresh data").click()


def _tree_entry(page, file_name: str):
    """The server tree's entry for one file.

    Callers assert visibility, not mere presence: the entry can sit in the DOM
    inside a collapsed group, which would pass while the user sees nothing.
    _open_app has cleared the persisted collapse state, so every group is
    expanded and no toggling is needed.

    Returns a locator for expect(), not a point-in-time lookup. The app
    re-renders the tree on its poll cycle, so wait_for() plus is_visible() can
    resolve the element, have it swapped out underneath, and report False
    having just waited successfully for it to appear. expect() retries until
    the condition holds.
    """
    return page.get_by_text(file_name, exact=False).first


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
    with _absent_from_host(f"{UI_QUADLET}.container"):
        _open_containers_tab(page)
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
            entries = _ssh(
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
        written = _ssh(f"cat {USER_QUADLET_DIR}/{shlex.quote(file_name)}")
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
    with _quadlet_on_host(f"{UI_QUADLET}.container") as file_name:
        _open_containers_tab(page, refresh=True)
        expect(_tree_entry(page, file_name)).to_be_visible(timeout=30000)


@pytest.mark.timeout(300)
def test_tree_drops_a_quadlet_deleted_on_the_host(page):
    """A file deleted on the host disappears from the server tree.

    This is the only end-to-end proof that the reconciler's DELETE reaches the UI.
    Nothing else covers the removal direction.
    """
    with _quadlet_on_host(f"{UI_QUADLET}.container") as file_name:
        _open_containers_tab(page, refresh=True)

        entry = _tree_entry(page, file_name)
        expect(entry).to_be_visible(timeout=30000)

        _remove_e2e_quadlet(file_name)
        expect(entry).not_to_be_visible(timeout=30000)


@pytest.mark.timeout(300)
def test_tree_picks_up_a_new_quadlet_without_a_manual_refresh(page):
    """The tree updates when a new quadlet is added without a manual reload.

    This is issue #319's acceptance criterion that the tree updates without a
    manual reload, and the podman suite is the only place where the reconcile,
    the SSE publish and the browser are all real at once.
    """
    with _absent_from_host(f"{E2E_PREFIX}sse-push.container") as file_name:
        # No refresh=True anywhere in this journey: the point is that the tree
        # updates on its own.
        _open_containers_tab(page)

        expect(page.get_by_text(file_name, exact=False)).to_have_count(0)

        _write_e2e_quadlet(file_name)

        expect(_tree_entry(page, file_name)).to_be_visible(timeout=60000)


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
    with _absent_from_host(file_name):
        _write_e2e_quadlet(file_name, content)
        # Separate from the write, unlike everything else here, because this is
        # the only unit that has to be visible to systemd and started.
        _ssh(
            f"systemctl --user daemon-reload && "
            f"systemctl --user start {shlex.quote(unit)}"
        )

        state = ""
        for _ in range(30):
            # check=False: is-active exits non-zero exactly when the unit is not
            # active, which is the answer this loop is waiting to change.
            state = _ssh(
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
    _open_app(page)
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
        _ssh(f"systemctl --user stop {shlex.quote(unit)}")

        # The row is keyed on the unit stem, which is the container name here,
        # so the same text identifies it before and after the stop.
        row = page.locator("#monitoring-stats-table table tbody tr").filter(
            has_text=running_monitor_container
        )
        expect(row).to_have_count(1, timeout=90000)
        expect(row).to_contain_text("inactive", timeout=90000)
        expect(row).not_to_contain_text("running")
    finally:
        _ssh(f"systemctl --user start {shlex.quote(unit)}")
