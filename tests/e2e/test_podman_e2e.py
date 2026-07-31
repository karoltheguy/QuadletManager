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


def _ssh(command: str) -> str:
    """Run a command on the podman host over plain ssh.

    The committed key is mode 644, which ssh refuses outright, so it is copied
    to a private temp file first. BatchMode=yes guarantees a failure rather than
    an interactive (and, with DISPLAY set, graphical) password prompt.
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
# exists for a documented reason and covers the whole suite; these three are the
# outliers. Each waits on a real host: a unit reaching active, a scanner pass, or
# a stats poll cycle, none of which are instant on a cold CI runner. The monitor
# journey below can legitimately spend 60s on the first and 90s on the last,
# which blows the global ceiling and fails as an opaque timeout rather than as
# the assertion that would name the problem.
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
    _ssh(
        f"mkdir -p {USER_QUADLET_DIR} && "
        f"printf '%s' '[Container]\\nImage=quay.io/quay/busybox:latest\\n' "
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


@pytest.mark.timeout(300)
def test_monitor_glance_bar_counts_a_really_running_container(page):
    """The Monitor glance bar reflects a container that is genuinely up.

    This is the behaviour changed in #276/#278, and the counts come from
    systemd unit state via the Quadlet inventory rather than from `podman ps`.
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
            state = _ssh(f"systemctl --user is-active {shlex.quote(unit)}").strip()
            if state == "active":
                break
            time.sleep(2)
        assert state == "active", (
            f"{unit} never became active on the host ({state!r}), so the glance "
            "bar assertion below would not be testing anything."
        )

        _open_app(page)
        page.get_by_role("button", name="Monitor").click()
        page.get_by_role("combobox").first.select_option(label=SERVER_LABEL)

        # Stats poll on an interval, so the count appears a cycle or two later.
        deadline = time.time() + 90
        text = ""
        while time.time() < deadline:
            text = page.locator("body").inner_text()
            if MONITOR_CONTAINER in text:
                break
            page.wait_for_timeout(2000)

        assert MONITOR_CONTAINER in text, (
            f"{MONITOR_CONTAINER} is active on the host but never appeared in "
            "the Monitor tab"
        )
    finally:
        _remove_e2e_quadlet(file_name)
