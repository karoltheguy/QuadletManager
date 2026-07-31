"""Fixtures for the `podman` suite: one test suite, two interchangeable hosts.

The target is chosen entirely by environment variables, read here and nowhere
else, and mirrored by scripts/seed_test_db.py. Test bodies never mention either
target, so adding a third costs one env lookup rather than a second code path.

    QM_PODMAN_HOST   default localhost:2223   "host:port", as servers.ip_address
    QM_PODMAN_USER   default editor           servers.ssh_user
    QM_PODMAN_KEY    default tests/fixtures/test_key
    QM_PODMAN_FORCE  when set, proceed despite leftover e2e- files

SAFETY. The loopback target runs against the developer's own machine and the
global-scope tests write to the real /etc/containers/systemd. Every file this
suite creates is named with the E2E_PREFIX below, and the teardown helper
*raises* rather than deletes anything that does not carry it. Do not add a
fixture whose name breaks that rule.
"""

import os
import shlex
import socket
from pathlib import Path

import aiosqlite
import pytest

from core.crypto import encrypt_private_key
from services.remote_fs import is_global_scope, quadlet_dir_for_scope
from services.ssh_manager import pool
from services.systemd_manager import systemctl_action

# The one safety rail the whole suite depends on. Changing it without changing
# every fixture filename in tests/fixtures/quadlets/ disarms the teardown guard.
E2E_PREFIX = "e2e-"

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "quadlets"

SCOPES = ("user", "global")

DEFAULT_HOST = "localhost:2223"
DEFAULT_USER = "editor"
DEFAULT_KEY = "tests/fixtures/test_key"


def target_address() -> str:
    return os.environ.get("QM_PODMAN_HOST", DEFAULT_HOST)


def target_host_port() -> tuple[str, int]:
    """Split the address the same way services/ssh_manager.py does."""
    address = target_address()
    if ":" in address:
        host, _, port = address.rpartition(":")
        return host, int(port)
    return address, 22


def fixture_content(name: str) -> str:
    """Read one quadlet fixture by file name."""
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def assert_safe_to_delete(path: str) -> None:
    """Refuse to touch anything that is not ours.

    Raises rather than skips. A test that cannot prove a path is its own has
    lost track of what it created, and on the loopback target the next step
    would delete a real unit off the developer's machine.
    """
    name = os.path.basename(path.rstrip("/"))
    if not name.startswith(E2E_PREFIX):
        raise RuntimeError(
            f"refusing to delete {path!r}: basename does not start with {E2E_PREFIX!r}. "
            "This suite only ever removes files it created."
        )


async def list_e2e_files(server_id: int, scope: str) -> list[str]:
    """Absolute paths of e2e- files currently in one scope's quadlet dir."""
    directory = await quadlet_dir_for_scope(server_id, scope)
    use_sudo = is_global_scope(scope)
    # `|| true` so a missing directory is an empty result, not an exception.
    listing = await pool.execute_command(
        server_id,
        f"ls -1 {shlex.quote(directory)} 2>/dev/null || true",
        use_sudo=use_sudo,
    )
    return [
        f"{directory}/{line.strip()}"
        for line in listing.splitlines()
        if line.strip().startswith(E2E_PREFIX)
    ]


async def remove_e2e_files(server_id: int, scope: str) -> list[str]:
    """Stop and delete every e2e- unit in one scope. Returns what it removed."""
    from services.quadlet_naming import unit_name_for

    paths = await list_e2e_files(server_id, scope)
    use_sudo = is_global_scope(scope)

    for path in paths:
        assert_safe_to_delete(path)

    # Stop first: deleting the file out from under a running unit leaves the
    # container alive with no unit to manage it.
    for path in paths:
        name = os.path.basename(path)
        if name.endswith(".container"):
            await systemctl_action(
                server_id, "stop", unit_name_for(name), scope=scope, allow_failure=True
            )

    for path in paths:
        await pool.execute_command(
            server_id, f"rm -f {shlex.quote(path)}", use_sudo=use_sudo
        )

    if paths:
        await systemctl_action(
            server_id, "daemon-reload", "", scope=scope, allow_failure=True
        )
    return paths


@pytest.fixture
def podman_target():
    """Target coordinates, or skip if nothing is listening.

    Skipping rather than failing matches the house convention in
    tests/test_ssh_systemd_integration.py: a developer without the test host up
    should get a skip, not a wall of red.
    """
    host, port = target_host_port()
    try:
        with socket.create_connection((host, port), timeout=2):
            pass
    except OSError:
        pytest.skip(
            f"No podman host on {host}:{port}. Start one with "
            "`./scripts/podman-e2e.sh up`, or point QM_PODMAN_HOST at your own."
        )
    return {
        "address": target_address(),
        "host": host,
        "port": port,
        "user": os.environ.get("QM_PODMAN_USER", DEFAULT_USER),
        "key_path": os.environ.get("QM_PODMAN_KEY", DEFAULT_KEY),
    }


@pytest.fixture
async def podman_server(podman_target, isolated_database, monkeypatch):
    """Register the podman host in this test's database and yield its server_id.

    Seeding happens per test because `isolated_database` is autouse and copies a
    fresh template for each one, so a server registered by an earlier test does
    not exist here.
    """
    # Must match what the app would use; CI uses 64 zeros.
    monkeypatch.setenv("QUADLET_MASTER_KEY", "0" * 64)

    key_path = Path(podman_target["key_path"])
    if not key_path.is_absolute():
        key_path = Path(__file__).resolve().parents[2] / key_path
    if not key_path.exists():
        pytest.skip(f"SSH key not found at {key_path}; set QM_PODMAN_KEY.")

    encrypted = encrypt_private_key(key_path.read_text(encoding="utf-8"))

    async with aiosqlite.connect(str(isolated_database)) as db:
        cursor = await db.execute(
            "INSERT INTO ssh_keys (key_name, encrypted_private_key) VALUES (?, ?)",
            ("podman_test_key", encrypted),
        )
        key_id = cursor.lastrowid
        cursor = await db.execute(
            "INSERT INTO servers (name, ip_address, ssh_user, ssh_key_id, scope_filter) "
            "VALUES (?, ?, ?, ?, 'both')",
            ("Podman Host", podman_target["address"], podman_target["user"], key_id),
        )
        server_id = cursor.lastrowid
        await db.commit()

    # The pool is a module-level singleton keyed by server_id, and per-test
    # databases reuse the same ids. Without this, test N+1 gets test N's
    # connection, pointed at a host that may no longer be the same one.
    await pool.close_all()

    await _preflight(server_id)

    try:
        yield server_id
    finally:
        # In a finally, not after the assertions: a failing test must still
        # clean up, or the next run trips the pre-flight check.
        for scope in SCOPES:
            try:
                await remove_e2e_files(server_id, scope)
            except Exception as exc:  # noqa: BLE001 - teardown must not mask the test's own failure
                print(f"warning: teardown failed for scope {scope}: {exc}")
        await pool.close_all()


async def _preflight(server_id: int) -> None:
    """Fail loudly if a previous run left files behind.

    Deliberately does not auto-delete. Leftovers mean a run crashed mid-way, and
    on the loopback target that directory is the developer's real one; deciding
    on their behalf that the contents are disposable is not this suite's call.
    """
    leftovers: list[str] = []
    for scope in SCOPES:
        leftovers.extend(await list_e2e_files(server_id, scope))

    if not leftovers:
        return

    if os.environ.get("QM_PODMAN_FORCE"):
        for scope in SCOPES:
            await remove_e2e_files(server_id, scope)
        return

    listing = "\n  ".join(leftovers)
    raise RuntimeError(
        "Leftover e2e- quadlet files found, which means a previous run did not "
        f"finish cleanly:\n  {listing}\n"
        "Inspect them, then re-run with QM_PODMAN_FORCE=1 to have the suite "
        "remove them for you."
    )
