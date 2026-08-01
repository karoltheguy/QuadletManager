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


def refuse_parallel_execution() -> None:
    """Refuse to run in parallel. This suite has exactly one host.

    Every test writes e2e- fixtures into the same two quadlet directories on
    the same machine, and the names are fixed, so two workers are two writers
    to one set of files. The pre-flight check below then does its job and
    refuses to start, because it finds files this worker did not write.

    Not hypothetical: `--dist=loadfile -n 2` in CI produced 16 errors from a
    single collision, gw0 tripping over the e2e-test.pod that gw1 had just
    installed.

    Called from the fixture rather than from pytest_configure, and that
    placement is the whole point. A conftest is imported whenever its
    directory is *collected*, even when every test in it is then deselected by
    -m, so a pytest_configure that raises here took down `unit`, `unmarked`,
    `integration` and `e2e` as well, all of which legitimately run -n auto and
    none of which go anywhere near this host.
    """
    worker_count = os.environ.get("PYTEST_XDIST_WORKER_COUNT")
    if worker_count and int(worker_count) > 1:
        raise RuntimeError(
            f"The podman suite must run serially, but pytest-xdist started "
            f"{worker_count} workers. Every test shares one host, one systemd "
            "instance and one set of e2e- fixture names. Drop -n, or use -n0."
        )


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


def generated_unit_name(file_name: str) -> str:
    """The unit name podman's generator actually produces for a quadlet file.

    Deliberately NOT services.quadlet_naming.unit_name_for, which maps every
    type to `<base>.service`. Only containers are named that way; podman suffixes
    the others by type. Verified against podman 5.8.4's generator:

        e2e-sleep.container -> e2e-sleep.service
        e2e-test.pod        -> e2e-test-pod.service
        e2e-test.volume     -> e2e-test-volume.service
        e2e-test.network    -> e2e-test-network.service

    Using the wrong name here is not cosmetic: teardown then stops a unit that
    does not exist, the real one keeps running, and its file is deleted out from
    under it. That is exactly how a pod and its infra container survived a
    full green run.
    """
    base, _, extension = file_name.rpartition(".")
    if extension == "container":
        return f"{base}.service"
    return f"{base}-{extension}.service"


async def remove_e2e_files(server_id: int, scope: str) -> list[str]:
    """Stop and delete every e2e- unit in one scope. Returns what it removed."""
    paths = await list_e2e_files(server_id, scope)
    use_sudo = is_global_scope(scope)

    for path in paths:
        assert_safe_to_delete(path)

    # Stop first, and stop *every* type. Deleting the file out from under a
    # running unit leaves the container or pod alive with nothing managing it.
    for path in paths:
        await systemctl_action(
            server_id,
            "stop",
            generated_unit_name(os.path.basename(path)),
            scope=scope,
            allow_failure=True,
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


async def sweep_e2e_podman_objects(server_id: int, scope: str) -> None:
    """Belt and braces: remove any leftover e2e- pods and containers.

    Stopping the units should be enough. This exists because on the loopback
    target a stray container keeps running on the developer's own machine, and
    because a test that creates a pod directly has nothing else sweeping up
    after it. Every name is checked against E2E_PREFIX first, so this can only
    ever remove objects this suite named.
    """
    from services.systemd_manager import ROOTLESS_ENV_PREFIX

    prefix = "" if is_global_scope(scope) else f"{ROOTLESS_ENV_PREFIX} "
    use_sudo = is_global_scope(scope)

    for kind, list_cmd, rm_cmd in (
        ("container", "podman ps -a --format '{{.Names}}'", "podman rm -f"),
        ("pod", "podman pod ps --format '{{.Name}}'", "podman pod rm -f"),
    ):
        listing = await pool.execute_command(
            server_id, f"{prefix}{list_cmd} 2>/dev/null || true", use_sudo=use_sudo
        )
        for name in (line.strip() for line in listing.splitlines()):
            if not name or not name.startswith(E2E_PREFIX):
                continue
            await pool.execute_command(
                server_id,
                f"{prefix}{rm_cmd} {shlex.quote(name)} 2>/dev/null || true",
                use_sudo=use_sudo,
            )


async def ensure_quadlet_dir(server_id: int, scope: str) -> str:
    """Create the scope's quadlet directory if it is not already there.

    The user-scope directory does not exist on a fresh account, and
    write_remote_file does not create parents.
    """
    directory = await quadlet_dir_for_scope(server_id, scope)
    use_sudo = is_global_scope(scope)
    await pool.execute_command(
        server_id, f"mkdir -p {shlex.quote(directory)}", use_sudo=use_sudo
    )
    return directory


async def install_fixture(server_id: int, scope: str, file_name: str) -> str:
    """Write one tests/fixtures/quadlets file into a scope. Returns its path."""
    from services.remote_fs import write_remote_file

    assert_safe_to_delete(file_name)  # every fixture must carry the prefix
    directory = await ensure_quadlet_dir(server_id, scope)
    path = f"{directory}/{file_name}"
    await write_remote_file(
        server_id, path, fixture_content(file_name), use_sudo=is_global_scope(scope)
    )
    return path


async def wait_for_active_state(
    server_id: int, unit_name: str, scope: str, expected: set[str], timeout: float = 60.0
) -> str:
    """Poll fetch_unit_states until ActiveState lands in `expected`.

    Starting a container is not instantaneous, and asserting immediately after
    `systemctl start` returns is the classic way to get a flaky suite.
    """
    import asyncio

    from services.systemd_manager import fetch_unit_states

    deadline = asyncio.get_event_loop().time() + timeout
    state = "(never queried)"
    while asyncio.get_event_loop().time() < deadline:
        states = await fetch_unit_states(server_id, [unit_name], scope=scope)
        state = states.get(unit_name, {}).get("active_state", "(absent)")
        if state in expected:
            return state
        await asyncio.sleep(2)
    raise AssertionError(
        f"{unit_name} in scope {scope} was {state!r} after {timeout}s; expected one of {expected}"
    )


@pytest.fixture
def podman_target():
    """Target coordinates, or skip if nothing is listening.

    Skipping rather than failing matches the house convention in
    tests/test_ssh_systemd_integration.py: a developer without the test host up
    should get a skip, not a wall of red.
    """
    refuse_parallel_execution()
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
                await sweep_e2e_podman_objects(server_id, scope)
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
