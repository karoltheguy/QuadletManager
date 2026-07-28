import logging
import re
import shlex
from services.ssh_manager import pool
from services.remote_fs import is_global_scope


logger = logging.getLogger("quadlet-manager.systemd")

# Allowlist for systemd unit names (supports template instances like foo@bar.service).
# Anything outside this set is rejected before the value ever reaches a shell.
_UNIT_NAME_RE = re.compile(r"^[a-zA-Z0-9_@\-\.:\\]+$")

# Rootless podman (and rootless `systemctl --user`) over non-interactive SSH
# needs XDG_RUNTIME_DIR so it can locate the user session (socket, cgroup
# delegates, etc.).  Without this the command either hangs or silently
# returns nothing.
ROOTLESS_ENV_PREFIX = 'XDG_RUNTIME_DIR=/run/user/$(id -u)'

_UNIT_SHOW_PROPERTIES = "Id,LoadState,ActiveState,SubState,NRestarts"


def build_unit_state_command(unit_names: list[str], scope: str) -> str:
    """Build the `systemctl show` command for a batch of unit names.

    Validates every name against _UNIT_NAME_RE and shell-quotes each before
    interpolation. Does NOT include `sudo` — callers apply their own sudo
    convention (either literally embedding `sudo ` or passing use_sudo=True
    to pool.execute_command).

    :param unit_names: The names of the systemd units to query.
    :param scope: Systemd scope ('global' or 'user').
    :return: The command string (without sudo).
    """
    for unit_name in unit_names:
        if not _UNIT_NAME_RE.match(unit_name):
            raise ValueError(f"Invalid unit name: {unit_name!r}")

    quoted_names = " ".join(shlex.quote(unit_name) for unit_name in unit_names)

    if scope == 'user':
        return f"{ROOTLESS_ENV_PREFIX} systemctl --user show {quoted_names} --property={_UNIT_SHOW_PROPERTIES}"
    return f"systemctl show {quoted_names} --property={_UNIT_SHOW_PROPERTIES}"


def parse_systemctl_show(output: str) -> dict:
    """Parse the stdout of `systemctl show ... --property=...` into a dict keyed by unit Id.

    Blocks are separated by a blank line; each block has one Key=Value pair per line.

    :param output: Raw stdout from `systemctl show`.
    :return: Dict mapping unit Id to a dict of load_state, active_state, sub_state, n_restarts.
    """
    result = {}
    blocks = output.split("\n\n")
    for block in blocks:
        fields = {}
        for line in block.splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()

        unit_id = fields.get("Id")
        if not unit_id:
            continue

        try:
            n_restarts = int(fields.get("NRestarts", 0))
        except (TypeError, ValueError):
            n_restarts = 0

        result[unit_id] = {
            "load_state": fields.get("LoadState"),
            "active_state": fields.get("ActiveState"),
            "sub_state": fields.get("SubState"),
            "n_restarts": n_restarts,
        }

    return result


async def fetch_unit_states(server_id: int, unit_names: list[str], scope: str = 'global') -> dict:
    """Fetch load/active/sub state and restart count for a list of systemd units.

    :param server_id: The server ID.
    :param unit_names: The names of the systemd units to query.
    :param scope: Systemd scope ('global' or 'user'). Defaults to 'global'.
    :return: Dict mapping unit Id to its parsed state, as returned by parse_systemctl_show.
    """
    if not unit_names:
        return {}

    cmd = build_unit_state_command(unit_names, scope)

    if scope == 'user':
        stdout = await pool.execute_command(server_id, cmd)
    else:
        stdout = await pool.execute_command(server_id, cmd, use_sudo=True)

    return parse_systemctl_show(stdout)


async def systemctl_action(server_id: int, action: str, unit_name: str, scope: str = 'global', allow_failure: bool = False):
    """Execute a systemctl action (start, stop, restart, status) on a unit.

    Applies user-level systemctl if scope is 'user', otherwise global.

    :param server_id: The server ID.
    :param action: The action (start, stop, restart, status, daemon-reload).
    :param unit_name: The name of the systemd unit.
    :param scope: Systemd scope ('global' or 'user'). Defaults to 'global'.
    :param allow_failure: When True, non-zero exit codes are logged and returned
                       as an error string rather than raising an exception.
                       Useful for daemon-reload / restart in the save flow,
                       where the file was already written successfully and we
                       don't want a restart hiccup to show as a save failure.
                       Defaults to False.
    """
    allowed_actions = ['start', 'stop', 'restart', 'status', 'daemon-reload']
    if action not in allowed_actions:
        raise ValueError(f"Invalid systemctl action: {action}")
        
    use_sudo = is_global_scope(scope)
    cmd_prefix = "systemctl"
    if scope == 'user':
        cmd_prefix = "systemctl --user"
        
    cmd = f"{cmd_prefix} {action}"
    if action != 'daemon-reload' and unit_name:
        if not _UNIT_NAME_RE.match(unit_name):
            raise ValueError(f"Invalid unit name: {unit_name!r}")
        cmd += f" {shlex.quote(unit_name)}"

    try:
        logger.info(f"Running '{cmd}' on server_id={server_id} (sudo={use_sudo})")
        return await pool.execute_command(server_id, cmd, use_sudo=use_sudo)
    except Exception as e:
        if allow_failure:
            logger.warning(f"Systemctl action '{action}' finished with non-zero exit (allow_failure=True): {e}")
            return "(warning: action did not complete cleanly, see server logs)"
        logger.error(f"Systemctl action failed: {e}")
        # Re-raise to let the API handle the HTTP 500
        raise

async def reload_and_restart(server_id: int, unit_name: str, scope: str = 'global'):
    """Trigger daemon-reload then restart a unit.

    This is typically done after a file is saved. Both steps use
    allow_failure=True so that a non-zero exit code from systemctl
    (e.g., if the unit fails to start after config changes) is logged
    as a warning instead of raising an exception that masks the successful
    file save.
    """
    await systemctl_action(server_id, 'daemon-reload', "", scope=scope, allow_failure=True)
    await systemctl_action(server_id, 'restart', unit_name, scope=scope, allow_failure=True)
