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

import os
import re
import shlex
import subprocess
import tempfile
import time

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
    _remove_e2e_quadlet(f"{UI_QUADLET}.container")
    try:
        _open_app(page)
        page.get_by_role("button", name="Containers").click()
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

        listing = ""
        for _ in range(20):
            listing = _ssh(f"ls -1 {USER_QUADLET_DIR}/ 2>/dev/null")
            if f"{UI_QUADLET}.container" in listing:
                break
            time.sleep(1)

        assert f"{UI_QUADLET}.container" in listing, (
            f"the modal reported success but no file reached the host: {listing!r}"
        )
    finally:
        _remove_e2e_quadlet(f"{UI_QUADLET}.container")


@pytest.mark.timeout(300)
def test_containers_tab_lists_a_quadlet_that_exists_on_the_host(page):
    """A file written directly on the host shows up in the server tree.

    The reverse direction from the test above: this one proves the scanner and
    the tree render what is really there, rather than what the UI just created.
    """
    file_name = f"{UI_QUADLET}.container"
    _remove_e2e_quadlet(file_name)

    # %b, not %s. printf '%s' does not expand \n, so the original wrote a single
    # literal line reading `[Container]\nImage=...`, which is not a quadlet at
    # all. The test passed anyway, because it only checks that the tree lists
    # the file name, and the scanner lists a file whatever is inside it.
    content = "[Container]\\nImage=quay.io/quay/busybox:latest\\n"
    _ssh(
        f"mkdir -p {USER_QUADLET_DIR} && "
        f"printf '%b' {shlex.quote(content)} "
        f"> {USER_QUADLET_DIR}/{shlex.quote(file_name)}"
    )
    try:
        _open_app(page)
        page.get_by_role("button", name="Containers").click()
        page.get_by_role("button", name="Refresh data").click()

        # Assert visibility, not mere presence: the entry can sit in the DOM
        # inside a collapsed group, which would pass while the user sees
        # nothing. _open_app has cleared the persisted collapse state, so every
        # group is expanded and no toggling is needed here.
        #
        # expect(), not wait_for() plus is_visible(). The app re-renders the
        # tree on its poll cycle, so a point-in-time check can resolve the
        # element, have it swapped out underneath, and report False having just
        # waited successfully for it to appear. expect() retries until the
        # condition holds.
        entry = page.get_by_text(file_name, exact=False).first
        expect(entry).to_be_visible(timeout=30000)
    finally:
        _remove_e2e_quadlet(file_name)


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
    _remove_e2e_quadlet(file_name)

    content = (
        "[Container]\\n"
        f"ContainerName={MONITOR_CONTAINER}\\n"
        "Image=quay.io/quay/busybox:latest\\n"
        "Exec=sh -c 'trap \"exit 0\" TERM; sleep 86400 & wait'\\n"
        "RunInit=yes\\n"
        "[Service]\\nRestart=no\\n"
        "[Install]\\nWantedBy=default.target\\n"
    )
    _ssh(
        f"mkdir -p {USER_QUADLET_DIR} && "
        f"printf '%b' {shlex.quote(content)} > {USER_QUADLET_DIR}/{shlex.quote(file_name)} && "
        f"systemctl --user daemon-reload && systemctl --user start {shlex.quote(unit)}"
    )
    try:
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
    finally:
        _remove_e2e_quadlet(file_name)


def _open_monitor_for_podman_host(page):
    _open_app(page)
    page.get_by_role("button", name="Monitor").click()
    page.get_by_role("combobox").first.select_option(label=SERVER_LABEL)


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

    # Stats arrive on a poll cycle, so the row appears a cycle or two later.
    # expect() retries; a point-in-time inner_text() can miss the re-render.
    row_name = page.locator("#monitoring-stats-table").get_by_text(
        running_monitor_container, exact=False
    ).first
    expect(row_name).to_be_visible(timeout=90000)


@pytest.mark.timeout(300)
@pytest.mark.xfail(
    strict=True,
    reason=(
        "#281: the glance bar's Total/Running/Stopped are computed from "
        "data.units, which _unit_names_for_scope reads out of the `quadlets` "
        "table. Nothing in production ever inserts into that table, only "
        "UPDATE, DELETE and reads, so units is always [] and the bar always "
        "reads 0. Flips to XPASS, and so to a failure, the day #281 is fixed."
    ),
)
def test_monitor_glance_bar_counts_a_really_running_container(
    page, running_monitor_container
):
    """The Monitor glance bar counts a container that is genuinely up.

    Executable form of #281 rather than a claim in a document. This suite is
    the only thing that can catch it end to end, since the bug needs a real
    host, a real running unit and the browser all at once.

    Deliberately waits for the stats table first. Both are written by the same
    updateMonitoringView call, so once the table has the row the payload has
    arrived and the bar has already been written. That keeps this at a short
    assertion timeout instead of burning 90s on every run to reach a failure
    that is expected, and it makes the failure specific: stats arrived, the
    table shows the container, and the bar still says 0.
    """
    _open_monitor_for_podman_host(page)

    table_row = page.locator("#monitoring-stats-table").get_by_text(
        running_monitor_container, exact=False
    ).first
    expect(table_row).to_be_visible(timeout=90000)

    # A positive integer, not exactly "1": once #281 is fixed the count covers
    # every quadlet-backed unit in the scope, and a host that legitimately has
    # others should not fail this.
    expect(page.locator("#mstat-running")).to_have_text(
        re.compile(r"^[1-9]\d*$"), timeout=15000
    )
