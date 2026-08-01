"""The full quadlet lifecycle, written once and run in both scopes.

Kept out of the test modules themselves so that `user` and `global` stay
separate files, because CI runs `--dist=loadfile`, which distributes by module,
and these two are the slowest things in the suite.

Not named test_*.py on purpose, so pytest does not collect it directly.
"""

import shlex

from services.quadlet_naming import unit_name_for
from services.remote_fs import is_global_scope
from services.ssh_manager import pool
from services.systemd_manager import (
    ROOTLESS_ENV_PREFIX,
    fetch_unit_states,
    reload_and_restart,
    systemctl_action,
)
from services.tree_scanner import fetch_all_quadlets

from tests.podman.conftest import (
    assert_safe_to_delete,
    install_fixture,
    wait_for_active_state,
)

FIXTURE = "e2e-sleep.container"
CONTAINER_NAME = "e2e-sleep"


def podman_prefix(scope: str) -> str:
    """Rootless podman needs XDG_RUNTIME_DIR; rootful needs sudo, applied by
    the caller via use_sudo."""
    return "" if is_global_scope(scope) else f"{ROOTLESS_ENV_PREFIX} "


async def running_container_names(server_id: int, scope: str) -> str:
    """`podman ps` output for the scope. Safe to run over SSH: unlike
    `podman run`, it starts no background daemon that would inherit our stdout
    and hold the channel open."""
    return await pool.execute_command(
        server_id,
        f"{podman_prefix(scope)}podman ps --format '{{{{.Names}}}}'",
        use_sudo=is_global_scope(scope),
    )


async def assert_full_lifecycle(server_id: int, scope: str) -> None:
    """write -> reload+start -> active -> discovered -> stop -> delete -> gone."""
    unit = unit_name_for(FIXTURE)

    # 1. Write the unit file where the generator will find it.
    path = await install_fixture(server_id, scope, FIXTURE)

    listing = await pool.execute_command(
        server_id, f"ls -1 {shlex.quote(path)}", use_sudo=is_global_scope(scope)
    )
    assert listing.strip() == path

    # 2. Generate the service and start it. This is the real generator run:
    #    daemon-reload is what invokes podman-system-generator on the file.
    await reload_and_restart(server_id, unit, scope=scope)

    # 3. systemd reports it up.
    state = await wait_for_active_state(
        server_id, unit, scope, expected={"active", "failed"}
    )
    assert state == "active", (
        f"{unit} did not reach active in scope {scope}. "
        "Check `journalctl` on the host for the generator's output."
    )

    # 4. podman agrees a container is actually running, not just that systemd
    #    thinks the unit succeeded.
    assert CONTAINER_NAME in await running_container_names(server_id, scope)

    # 5. The scanner discovers it. This is what populates the server tree.
    discovered = await fetch_all_quadlets(server_id, scope_filter=scope)
    names = [entry["name"] for entry in discovered[scope]]
    assert FIXTURE in names, f"{FIXTURE} not in {scope} scan results: {names}"

    # 6. Stop it.
    await systemctl_action(server_id, "stop", unit, scope=scope)
    state = await wait_for_active_state(
        server_id, unit, scope, expected={"inactive", "failed"}
    )
    assert state == "inactive", f"{unit} was {state!r} after stop"
    assert CONTAINER_NAME not in await running_container_names(server_id, scope)

    # 7. Delete the file and reload; the unit must stop existing entirely.
    assert_safe_to_delete(path)
    await pool.execute_command(
        server_id, f"rm -f {shlex.quote(path)}", use_sudo=is_global_scope(scope)
    )
    await systemctl_action(server_id, "daemon-reload", "", scope=scope)

    states = await fetch_unit_states(server_id, [unit], scope=scope)
    load_state = states.get(unit, {}).get("load_state", "not-found")
    assert load_state == "not-found", (
        f"{unit} still loads as {load_state!r} after its file was removed; "
        "the generator output was not cleaned up by daemon-reload"
    )
