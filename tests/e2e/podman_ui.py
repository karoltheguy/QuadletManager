"""Shared podman-host UI helpers for browser journeys against a real host.

Not a conftest: these are imported explicitly by the modules that need them
(tests/e2e/test_podman_e2e.py, tests/e2e/test_status_dots.py,
tests/e2e/test_stats_e2e.py) rather than being injected implicitly into every
test in the package, most of which have nothing to do with a podman host.
"""

import contextlib
import os
import shlex
import subprocess
import tempfile
import urllib.request

from tests.app_url import BASE_URL
SERVER_LABEL = "Podman Host"

# Same env contract as tests/podman/conftest.py.
PODMAN_HOST = os.environ.get("QM_PODMAN_HOST", "localhost:2223")
PODMAN_USER = os.environ.get("QM_PODMAN_USER", "editor")
PODMAN_KEY = os.environ.get("QM_PODMAN_KEY", "tests/fixtures/test_key")

E2E_PREFIX = "e2e-"

USER_QUADLET_DIR = "~/.config/containers/systemd"

# %b, not %s. printf '%s' does not expand \n, so writing this with %s produces a
# single literal line reading `[Container]\nImage=...`, which is not a quadlet at
# all. A test that only checks the tree lists the file name still passes, because
# the scanner lists a file whatever is inside it.
BUSYBOX_QUADLET = "[Container]\\nImage=quay.io/quay/busybox:latest\\n"


def ssh(command: str, check: bool = True) -> str:
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


def remove_e2e_quadlet(file_name: str) -> None:
    """Stop and delete one of our quadlets. Prefix-guarded, as everywhere else."""
    assert file_name.startswith(E2E_PREFIX), f"refusing to remove {file_name!r}"
    unit = f"{file_name.rsplit('.', 1)[0]}.service"
    ssh(
        f"systemctl --user stop {shlex.quote(unit)} 2>/dev/null; "
        f"rm -f {USER_QUADLET_DIR}/{shlex.quote(file_name)}; "
        f"systemctl --user daemon-reload"
    )


def write_e2e_quadlet(file_name: str, content: str = BUSYBOX_QUADLET) -> None:
    """Write one of our quadlets into the user quadlet dir. Prefix-guarded.

    Does not daemon-reload: callers that need systemd to see the unit issue
    that themselves, and the tests that only watch the reconciler do not.
    """
    assert file_name.startswith(E2E_PREFIX), f"refusing to write {file_name!r}"
    ssh(
        f"mkdir -p {USER_QUADLET_DIR} && "
        f"printf '%b' {shlex.quote(content)} "
        f"> {USER_QUADLET_DIR}/{shlex.quote(file_name)}"
    )


def podman_host_is_seeded(base_url: str) -> bool:
    """True when the app at base_url lists a server named SERVER_LABEL."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/servers/options", timeout=5) as resp:
            body = resp.read().decode()
        return SERVER_LABEL in body
    except Exception:
        return False


def skip_unless_seeded(base_url: str) -> None:
    import pytest

    if not podman_host_is_seeded(base_url):
        pytest.skip(
            f"no server named '{SERVER_LABEL}' at {base_url}; seed it with "
            "scripts/seed_test_db.py (an app that requires a login looks the "
            "same from here, since this check reads plain HTTP with no cookie)"
        )


@contextlib.contextmanager
def absent_from_host(file_name: str):
    """Guarantee the file is gone before the block and again after it.

    The leading removal is not paranoia: this suite runs against one long-lived
    host, so a previous run that died between creating a file and its teardown
    would otherwise hand the next run a tree that already contains the entry it
    is about to assert appears.
    """
    remove_e2e_quadlet(file_name)
    try:
        yield file_name
    finally:
        remove_e2e_quadlet(file_name)


@contextlib.contextmanager
def quadlet_on_host(file_name: str, content: str = BUSYBOX_QUADLET):
    """Put one quadlet on the host for the duration of the block, then remove it.

    Removal inside the block is fine and is what the deletion journey does: the
    teardown here is `rm -f`, so removing an already-removed file is a no-op.
    """
    with absent_from_host(file_name):
        write_e2e_quadlet(file_name, content)
        yield file_name


def open_app(page):
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


def open_containers_tab(page, refresh: bool = False):
    """Land on the Containers tab with the tree in a known, expanded state.

    `refresh` clicks Refresh server list, which is what a journey wants when it wrote
    a file on the host a moment ago and does not want to wait out a reconcile
    cycle. The journey that is specifically about updating *without* a manual
    refresh must leave it off.
    """
    open_app(page)
    page.get_by_role("button", name="Containers").click()
    if refresh:
        page.get_by_role("button", name="Refresh server list").click()


def tree_entry(page, file_name: str):
    """The server tree's entry for one file.

    Callers assert visibility, not mere presence: the entry can sit in the DOM
    inside a collapsed group, which would pass while the user sees nothing.
    open_app has cleared the persisted collapse state, so every group is
    expanded and no toggling is needed.

    Returns a locator for expect(), not a point-in-time lookup. The app
    re-renders the tree on its poll cycle, so wait_for() plus is_visible() can
    resolve the element, have it swapped out underneath, and report False
    having just waited successfully for it to appear. expect() retries until
    the condition holds.
    """
    return page.get_by_text(file_name, exact=False).first
