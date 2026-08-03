"""Ask a real sudo whether the published allowlist is enough to run the app.

This is the test issue #289 says was missing, and it is missing for a structural
reason rather than an oversight. The container target's `editor` account holds
`NOPASSWD:ALL`, so no test running as `editor` can ever observe a too-narrow
policy. The gap was found only when the loopback target installed the published
eight rules on a real machine and global scope stopped working.

`Dockerfile.podman-host` now also creates a `narrow` account holding exactly
those eight rules. This test SSHes in as that account and asks, for every
command `docs/SUDO_PERMISSIONS.md` records the app running under sudo, whether
sudo permits it.

The probe is `sudo -n -l -- <command>`, which is a policy query and nothing
else: it prints the resolved command if permitted, exits non-zero if not, and
runs nothing either way. So this test writes no files, starts no units, needs no
teardown, imposes no ordering on the rest of the suite, and cannot leak, which
matters in a suite whose design is largely about not leaking.

`-n` is what makes a denial legible. Without it, a command that falls outside
the allowlist makes sudo try to authenticate, which over a non-interactive SSH
session produces "a terminal is required to read the password" rather than
"not allowed to execute". That is the same confusing error a user hits, and it
is worth knowing that is what a denial looks like in production.

TARGETS. On the container target the account is `narrow` and needs nothing set.
On the loopback target the SSH account *is* the narrow account, so run with
QM_PODMAN_NARROW_USER=$LOOPBACK_USER; `scripts/podman-e2e.sh setup-local` prints
the full command line.
"""

import os
import shlex
import subprocess
import tempfile

import pytest

from tests.podman.conftest import target_host_port
from tests.sudo_permissions import required_commands

pytestmark = pytest.mark.podman

NARROW_USER = os.environ.get("QM_PODMAN_NARROW_USER", "narrow")
PODMAN_KEY = os.environ.get("QM_PODMAN_KEY", "tests/fixtures/test_key")

COMMANDS = required_commands()


def _ssh_as_narrow(command: str) -> subprocess.CompletedProcess:
    """Run one command on the host as the narrow account.

    Plain ssh rather than `pool.execute_command`, because the pool resolves its
    credentials from a `servers` row and every such row in this suite is the
    privileged account. The whole point here is to connect as a different user.

    The committed key is mode 644, which ssh refuses outright, so it is copied
    to a private temp file first. Returns the CompletedProcess rather than
    raising: a non-zero exit is the answer this test is asking for.
    """
    host, port = target_host_port()

    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        with open(PODMAN_KEY, encoding="utf-8") as key:
            handle.write(key.read())
        key_copy = handle.name
    os.chmod(key_copy, 0o600)
    try:
        return subprocess.run(
            [
                "ssh", "-i", key_copy, "-p", str(port),
                "-o", "BatchMode=yes",
                "-o", "PreferredAuthentications=publickey",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "LogLevel=ERROR",
                "-o", "ConnectTimeout=10",
                f"{NARROW_USER}@{host}", command,
            ],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        os.unlink(key_copy)


def _probe(argv: list[str]) -> subprocess.CompletedProcess:
    quoted = " ".join(shlex.quote(part) for part in argv)
    return _ssh_as_narrow(f"sudo -n -l -- {quoted}")


@pytest.fixture(scope="module")
def narrow_account_reachable():
    """Fail loudly, not quietly, when the account is missing or unreachable.

    Skipping here would be worse than useless. Every assertion below is of the
    form "sudo permits this", so an unreachable account produces a green run
    that checked nothing, on the one test whose entire job is to notice
    something nobody noticed for twelve CI rounds.
    """
    result = _ssh_as_narrow("id -un")
    detail = (
        f"  exit: {result.returncode}\n"
        f"  stdout: {result.stdout.strip()!r}\n"
        f"  stderr: {result.stderr.strip()!r}\n"
        "On the container target this account comes from Dockerfile.podman-host; "
        "rebuild the image if it predates it. On the loopback target, set "
        "QM_PODMAN_NARROW_USER to the account scripts/podman-e2e.sh created."
    )

    assert result.returncode == 0, (
        f"could not reach {NARROW_USER!r} on the podman host, so none of the "
        f"policy probes below would be testing anything.\n{detail}"
    )
    assert result.stdout.strip() == NARROW_USER, (
        f"ssh connected but landed on a different account than {NARROW_USER!r}, "
        "so the probes below would report some other account's policy.\n"
        f"{detail}"
    )


@pytest.mark.timeout(120)
def test_the_narrow_account_is_not_privileged(narrow_account_reachable):
    """Guard the guard: an account with blanket sudo would pass everything.

    Cheap, and it protects against the exact mistake that produced #289. Adding
    this account to wheel, or reusing `editor` by setting
    QM_PODMAN_NARROW_USER=editor, turns every assertion in this file into a
    tautology while leaving it green.
    """
    result = _probe(["/usr/bin/id"])
    assert result.returncode != 0, (
        f"{NARROW_USER!r} is permitted to run /usr/bin/id, which the documented "
        "allowlist does not grant. This account holds broader sudo rights than "
        "the policy under test, so every other assertion in this file passes "
        "regardless of what the allowlist says."
    )


@pytest.mark.timeout(300)
def test_documented_allowlist_permits_every_command_the_app_runs(
    narrow_account_reachable,
):
    """Every row of the need list, against the real policy.

    One test rather than one per row, deliberately. The state being asserted is
    "the policy is sufficient", which is a single fact; parametrizing it would
    report twelve expected failures next to six passes and make the suite's
    summary line unreadable. The assertion message carries the full breakdown,
    which is where it is useful.
    """
    denied = []
    for command in COMMANDS:
        result = _probe(command.argv)
        if result.returncode != 0:
            denied.append((command, result.stderr.strip()))

    assert not denied, (
        "the documented sudoers allowlist does not permit "
        f"{len(denied)} of the {len(COMMANDS)} commands the app runs under "
        "sudo. Global scope is broken on any server set up by the "
        "documentation.\n\n"
        + "\n".join(
            f"  {command.probe}\n"
            f"      call site: {command.call_site}\n"
            f"      sudo said: {message}"
            for command, message in denied
        )
        + "\n\nThe need list lives in docs/SUDO_PERMISSIONS.md."
    )
